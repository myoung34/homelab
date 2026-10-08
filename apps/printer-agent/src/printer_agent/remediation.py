"""Configuration remediation (phase 4).

  propose  structured section/option edits -> minimal diff, validation,
           computed risk; stored. No side effects on the printer.
  apply    [human approval in kagent] base hash must still match, printer
           idle, backup, upload, RESTART, verify the running config contains
           the change; automatic rollback if Klipper does not come back ready.
  open_pr  [human approval] apply the same edits to the Git *seed*
           ConfigMap on a new branch and open a PR. Never merges.

In the homelab the ConfigMap is only a first-boot seed, so the PR keeps Git
in step with the printer; it does not deploy anything to the printer itself.
"""

from __future__ import annotations

import base64
import contextlib
import difflib
import logging
import re
import secrets
import time
from dataclasses import asdict
from typing import Any

import httpx

from printer_agent import klipper_config, service
from printer_agent.gitrepo import extract_configmap_key, replace_configmap_key
from printer_agent.inventory import Printer
from printer_agent.klipper_config import Edit, EditError
from printer_agent.moonraker import MoonrakerAPIError, MoonrakerError
from printer_agent.operations import Op, _require_idle, _sleep, poll
from printer_agent.safety import PreconditionFailedError, RiskLevel
from printer_agent.service import Context
from printer_agent.store import sha256

logger = logging.getLogger(__name__)
PROPOSAL_TTL = 3600.0
BACKUP_DIR = "printer-agent-backups"


def _unified(old: str, new: str, name: str) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{name}",
            tofile=f"b/{name}",
            n=3,
        )
    )


def change_key(section: str, option: str | None) -> str:
    return f"{section}/{option}" if option else section


async def propose(
    ctx: Context,
    printer: Printer,
    edits: list[dict[str, Any]],
    *,
    summary: str,
    rationale: str,
    evidence: list[str],
) -> dict[str, Any]:
    if not edits:
        raise PreconditionFailedError("no edits given")
    if not summary.strip() or not rationale.strip():
        raise PreconditionFailedError("summary and rationale are required: speculative changes are not proposed")
    if not evidence:
        raise PreconditionFailedError("evidence is required (the observations that justify this change)")
    parsed = [
        Edit(str(e["section"]), str(e["option"]), None if e.get("value") is None else str(e["value"])) for e in edits
    ]
    client = ctx.client(printer)
    raw = (await client.download("config", printer.klipper.config_file, max_bytes=2_000_000)).decode("utf-8")
    raw_cfg = klipper_config.parse(raw)
    for e in parsed:
        sec = " ".join(e.section.split())
        if sec not in raw_cfg.user and sec not in raw_cfg.autosave and raw_cfg.includes:
            raise PreconditionFailedError(
                f"[{sec}] is not in {printer.klipper.config_file} itself (it may live in an included file: "
                f"{raw_cfg.includes}); editing included files is not supported"
            )
    try:
        new = klipper_config.apply_edits(raw, parsed)
    except EditError as err:
        raise PreconditionFailedError(str(err)) from err
    new_cfg = klipper_config.parse(new)
    changes = klipper_config.semantic_diff(raw_cfg, new_cfg)
    if not changes:
        raise PreconditionFailedError("the edits do not change the effective configuration")
    serial = printer.hardware.mcu.get("serial")
    before = {(f.code, f.section, f.option) for f in klipper_config.validate(raw_cfg, expected_mcu_serial=serial)}
    after_findings = klipper_config.validate(new_cfg, expected_mcu_serial=serial)
    introduced = [
        f
        for f in after_findings
        if (f.code, f.section, f.option) not in before and f.severity in ("error", "danger", "warning")
    ]
    blocking = [f for f in introduced if f.severity in ("error", "danger")]
    resolved = [
        {"code": c, "section": s, "option": o}
        for c, s, o in before
        if (c, s, o) not in {(f.code, f.section, f.option) for f in after_findings}
    ]
    risk = klipper_config.max_risk(changes)
    dangerous = [change_key(c.section, c.option) for c in changes if c.risk >= RiskLevel.DANGEROUS]
    autosave_edits = [change_key(c.section, c.option) for c in changes if c.autosave]
    now = ctx.clock.now()
    proposal = {
        "id": f"p-{printer.id}-{int(now)}-{secrets.token_hex(3)}",
        "printer": printer.id,
        "created_at": now,
        "expires_at": now + PROPOSAL_TTL,
        "status": "proposed",
        "summary": summary.strip(),
        "rationale": rationale.strip(),
        "evidence": evidence,
        "edits": [asdict(e) for e in parsed],
        "base_sha": sha256(raw),
        "new_text": new,
        "old_text": raw,
        "diff": _unified(raw, new, printer.klipper.config_file),
        "changes": [c.to_dict() for c in changes],
        "risk": risk.name,
        "dangerous_changes": dangerous,
        "validation": {
            "passed": not blocking,
            "introduced_problems": [f.to_dict() for f in introduced],
            "resolved_problems": resolved,
            "remaining": [f.to_dict() for f in after_findings if f.severity in ("error", "danger")],
        },
    }
    ctx.store.save_proposal(proposal)
    ctx.auditor.record(
        action="config_propose",
        printer_id=printer.id,
        risk=RiskLevel.SAFE_AUTOMATION,
        outcome="proposed",
        params={"proposal": proposal["id"], "edits": proposal["edits"]},
    )
    allowed = min(ctx.policy.max_risk, printer.policy.max_risk)
    return {
        "proposal_id": proposal["id"],
        "summary": proposal["summary"],
        "diff": proposal["diff"],
        "changes": proposal["changes"],
        "risk": risk.name,
        "policy_allows_apply": risk <= allowed,
        "policy_max_risk": allowed.name,
        "dangerous_changes": dangerous,
        "save_config_block_edits": autosave_edits,
        "validation": proposal["validation"],
        "expires_in_s": PROPOSAL_TTL,
        "next": (
            "nothing has been changed. To apply: printer_config_apply(proposal_id"
            + (", acknowledge_dangerous=[...each dangerous change...]" if dangerous else "")
            + ")"
        ),
    }


def _load(ctx: Context, printer: Printer, proposal_id: str, *, statuses: tuple[str, ...]) -> dict[str, Any]:
    p = ctx.store.get_proposal(proposal_id)
    if p is None or p["printer"] != printer.id:
        raise PreconditionFailedError(f"no proposal {proposal_id!r} for {printer.id}")
    if p["status"] not in statuses:
        raise PreconditionFailedError(f"proposal is '{p['status']}', expected one of {statuses}")
    return p


async def apply(
    ctx: Context,
    printer: Printer,
    proposal_id: str,
    *,
    acknowledge_dangerous: list[str] | None = None,
    restart_timeout: float = 90.0,
) -> dict[str, Any]:
    p = _load(ctx, printer, proposal_id, statuses=("proposed",))
    risk = RiskLevel[p["risk"]]
    op = Op(ctx, printer, "config_apply", risk, {"proposal": proposal_id, "edits": p["edits"]})
    op.authorize()
    if ctx.clock.now() > p["expires_at"]:
        op.audit("precondition_failed", "expired")
        raise PreconditionFailedError("proposal expired; propose again against the current config")
    if not p["validation"]["passed"]:
        op.audit("precondition_failed", "validation failed")
        raise PreconditionFailedError(
            "proposal failed validation", {"problems": p["validation"]["introduced_problems"]}
        )
    missing = sorted(set(p["dangerous_changes"]) - set(acknowledge_dangerous or []))
    if missing:
        op.audit("precondition_failed", f"unacknowledged dangerous changes {missing}")
        raise PreconditionFailedError(
            "dangerous changes must each be acknowledged explicitly", {"unacknowledged": missing}
        )
    await _require_idle(ctx, printer, op)
    client = ctx.client(printer)
    current = (await client.download("config", printer.klipper.config_file, max_bytes=2_000_000)).decode("utf-8")
    if sha256(current) != p["base_sha"]:
        op.audit("precondition_failed", "base changed")
        raise PreconditionFailedError(
            "printer.cfg changed since the proposal was made (SAVE_CONFIG or a manual edit); propose again"
        )
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(ctx.clock.now()))
    backup = f"{BACKUP_DIR}/{printer.klipper.config_file.rsplit('.', 1)[0]}-{stamp}-{p['base_sha'][:8]}.cfg"
    try:
        await client.upload("config", backup, current.encode("utf-8"))
        await client.upload("config", printer.klipper.config_file, p["new_text"].encode("utf-8"))
    except MoonrakerError as err:
        return op.result(ok=False, verified=False, message=f"upload failed before restart: {err}", backup=backup)
    op.audit("executed", f"uploaded; backup {backup}")
    restart_ok, state_msg = await _restart_and_wait(ctx, printer, restart_timeout)
    if not restart_ok:
        rolled = await _rollback(ctx, printer, current, restart_timeout)
        p["status"] = "rolled_back" if rolled else "failed"
        ctx.store.save_proposal(p)
        return op.result(
            ok=False,
            verified=False,
            message=f"Klipper did not come back ready with the new config ({state_msg}). "
            + (
                "Rolled back to the previous printer.cfg and verified Klipper is ready."
                if rolled
                else "ROLLBACK ALSO FAILED - printer needs attention."
            ),
            backup=backup,
            rolled_back=rolled,
        )
    loaded = klipper_config.parse(await service.loaded_config_text(ctx, printer))
    mismatches = []
    for e in p["edits"]:
        got = loaded.value(" ".join(e["section"].split()), e["option"].lower())
        want = e["value"]
        if (want is None and got is not None) or (
            want is not None and klipper_config._norm(got) != klipper_config._norm(want)
        ):
            mismatches.append({"section": e["section"], "option": e["option"], "expected": want, "running": got})
    now = ctx.clock.now()
    ctx.store.record_config(printer.id, "file", p["new_text"], ts=now, source="apply")
    ctx.store.record_config(
        printer.id,
        "loaded",
        service.canonical(service.config_dict_to_text(loaded.to_dict())),
        ts=now,
        source="apply",
    )
    p["status"] = "applied" if not mismatches else "applied_unverified"
    p["applied_at"] = now
    p["backup"] = backup
    ctx.store.save_proposal(p)
    if mismatches:
        return op.result(
            ok=True,
            verified=False,
            message="applied and Klipper is ready, but the running config does not show every edited value",
            mismatches=mismatches,
            backup=backup,
        )
    return op.result(
        ok=True,
        verified=True,
        message="applied: printer.cfg uploaded, Klipper restarted and is ready, and the running config "
        "contains every edited value. No motion or heating was performed.",
        backup=backup,
        diff=p["diff"],
        next="printer_config_open_pr to sync the Git seed (requires approval)",
    )


async def _restart_and_wait(ctx: Context, printer: Printer, timeout: float) -> tuple[bool, str | None]:
    client = ctx.client(printer)
    try:
        await client.restart()
    except MoonrakerAPIError as err:
        return False, f"restart rejected: {err}"

    async def ready() -> bool:
        return str((await client.server_info()).get("klippy_state")) == "ready"

    await _sleep(2.0)
    ok = await poll(ready, timeout=timeout)
    msg = None
    with contextlib.suppress(MoonrakerError):
        msg = (await client.printer_info()).get("state_message")
    return ok, msg


async def _rollback(ctx: Context, printer: Printer, original: str, timeout: float) -> bool:
    try:
        await ctx.client(printer).upload("config", printer.klipper.config_file, original.encode("utf-8"))
    except MoonrakerError:
        logger.exception("rollback upload failed for %s", printer.id)
        return False
    ok, _ = await _restart_and_wait(ctx, printer, timeout)
    ctx.auditor.record(
        action="config_rollback",
        printer_id=printer.id,
        risk=RiskLevel.HIGH_RISK_WRITE,
        outcome="verified" if ok else "failed",
    )
    return ok


# ------------------------------------------------------------------- PR


class GitHub:
    def __init__(self, token: str, repo: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.repo = repo
        self._c = httpx.AsyncClient(
            base_url="https://api.github.com",
            timeout=20.0,
            transport=transport,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    async def aclose(self) -> None:
        await self._c.aclose()

    async def req(self, method: str, path: str, **kw: Any) -> Any:
        r = await self._c.request(method, f"/repos/{self.repo}{path}", **kw)
        if r.status_code >= 400:
            raise PreconditionFailedError(f"GitHub {method} {path} -> {r.status_code}: {r.text[:300]}")
        return r.json()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


def commit_message(printer: Printer, p: dict[str, Any]) -> str:
    subject = p["summary"]
    if not re.match(r"^\w+(\([^)]+\))?: ", subject):
        subject = f"fix(klipper): {subject}"
    if printer.id not in subject:
        subject = f"{subject} for {printer.id}"
    changes = "\n".join(
        f"- [{c['section']}] {c.get('option', '')}: {c.get('old')!r} -> {c.get('new')!r} ({c['risk']})"
        for c in p["changes"]
    )
    evidence = "\n".join(f"- {e}" for e in p["evidence"])
    applied = (
        f"Applied to the live printer at {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(p['applied_at']))} "
        "and verified in the running config."
        if p.get("applied_at")
        else "NOT yet applied to the live printer."
    )
    return (
        f"{subject[:72]}\n\nWhat changed (printer: {printer.id}):\n{changes}\n\nWhy:\n{p['rationale']}\n\n"
        f"Evidence:\n{evidence}\n\n{applied}\nThe ConfigMap is the first-boot seed; this keeps it in step "
        f"with the printer's PVC copy.\n\nProposal: {p['id']} (printer-agent)"
    )


async def open_pr(
    ctx: Context,
    printer: Printer,
    proposal_id: str,
    *,
    allow_unapplied: bool = False,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    statuses = ("applied", "applied_unverified", "proposed") if allow_unapplied else ("applied",)
    p = _load(ctx, printer, proposal_id, statuses=statuses)
    op = Op(ctx, printer, "config_open_pr", RiskLevel.HIGH_RISK_WRITE, {"proposal": proposal_id})
    op.authorize()
    if not ctx.settings.github_token:
        op.audit("precondition_failed", "no token")
        raise PreconditionFailedError(
            "GITHUB_TOKEN is not configured (Vault secret printer-agent); the diff can still be applied by hand",
            {"diff": p["diff"]},
        )
    if printer.git is None:
        raise PreconditionFailedError(f"{printer.id} has no git seed path in printers.yaml")
    gh = GitHub(ctx.settings.github_token, ctx.settings.github_repo, transport)
    try:
        base = ctx.settings.git_branch
        ref = await gh.req("GET", f"/git/ref/heads/{base}")
        base_sha = ref["object"]["sha"]
        f = await gh.req("GET", f"/contents/{printer.git.path}", params={"ref": base})
        manifest = base64.b64decode(f["content"]).decode("utf-8")
        seed = extract_configmap_key(manifest, printer.git.key)
        try:
            new_seed = klipper_config.apply_edits(seed, [Edit(**e) for e in p["edits"]])
        except EditError as err:
            raise PreconditionFailedError(f"cannot apply the same edits to the Git seed: {err}") from err
        if new_seed == seed:
            return op.result(
                ok=True,
                verified=True,
                message="the Git seed already contains this change; no PR needed",
            )
        new_manifest = replace_configmap_key(manifest, printer.git.key, new_seed)
        branch = f"printer-agent/{printer.id}-{_slug(p['summary'])}-{int(ctx.clock.now())}"
        if branch in (base, "main", "master"):
            raise PreconditionFailedError("refusing to write to the default branch")
        await gh.req("POST", "/git/refs", json={"ref": f"refs/heads/{branch}", "sha": base_sha})
        msg = commit_message(printer, p)
        await gh.req(
            "PUT",
            f"/contents/{printer.git.path}",
            json={
                "message": msg,
                "branch": branch,
                "sha": f["sha"],
                "content": base64.b64encode(new_manifest.encode("utf-8")).decode("ascii"),
            },
        )
        body = (
            msg.split("\n", 2)[2]
            + "\n\n<details><summary>printer.cfg diff (live printer)</summary>\n\n```diff\n"
            + p["diff"]
            + "\n```\n</details>\n\nOpened by printer-agent after operator approval. Merging syncs the "
            "seed ConfigMap via Argo CD; it does not restart or reconfigure the printer."
        )
        pr = await gh.req(
            "POST",
            "/pulls",
            json={
                "title": msg.split("\n", 1)[0],
                "head": branch,
                "base": base,
                "body": body,
                "draft": False,
            },
        )
        check = await gh.req("GET", f"/pulls/{pr['number']}")
        files = await gh.req("GET", f"/pulls/{pr['number']}/files")
        verified = (
            check.get("state") == "open"
            and check["head"]["ref"] == branch
            and [x["filename"] for x in files] == [printer.git.path]
        )
        p["pr_url"] = check.get("html_url")
        ctx.store.save_proposal(p)
        return op.result(
            ok=True,
            verified=verified,
            message=(
                f"opened PR #{pr['number']} ({check.get('html_url')}); read back: state "
                f"{check.get('state')}, branch {check['head']['ref']}, files "
                f"{[x['filename'] for x in files]}. Not merged - merging is the operator's call."
            ),
            pr_url=check.get("html_url"),
            branch=branch,
        )
    except (httpx.HTTPError, KeyError) as err:
        return op.result(ok=False, verified=False, message=f"GitHub interaction failed: {err}")
    finally:
        await gh.aclose()
