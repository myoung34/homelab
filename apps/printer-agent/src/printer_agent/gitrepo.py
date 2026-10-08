"""Read-only access to the homelab repository.

A bare, blob-less partial clone of the (public) repo is kept on the data
volume and fetched on demand (TTL). Only read commands are ever run; refs are
validated and every path must sit under an allowlisted prefix.

kagent's GitHub tools (via Aperture) cannot return file bodies, which is why
this server holds its own clone.
"""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/~^@{}-]{0,200}$")
_SEP = "\x1f"
_REC = "\x1e"


class GitError(Exception):
    pass


class GitPathNotAllowedError(GitError):
    pass


@dataclass(slots=True)
class Commit:
    sha: str
    date: float
    author: str
    subject: str
    body: str
    files: list[str]

    def to_dict(self, *, with_body: bool = False) -> dict[str, Any]:
        d: dict[str, Any] = {
            "sha": self.sha[:12],
            "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.date)),
            "author": self.author,
            "subject": self.subject,
            "files": self.files,
        }
        if with_body and self.body.strip():
            d["body"] = self.body.strip()
        return d


class GitRepo:
    def __init__(
        self,
        url: str,
        path: Path,
        *,
        branch: str = "main",
        allowed_paths: tuple[str, ...] = (),
        fetch_ttl: float = 120.0,
        timeout: float = 120.0,
    ) -> None:
        self.url = url
        self.path = path
        self.branch = branch
        self.allowed = tuple(p.rstrip("/") + "/" for p in allowed_paths)
        self.fetch_ttl = fetch_ttl
        self.timeout = timeout
        self._last_fetch = 0.0
        self._lock = asyncio.Lock()

    # ----------------------------------------------------------- plumbing

    def _run(self, *args: str, cwd: Path | None = None) -> str:
        cmd = ["git", *args]
        try:
            proc = subprocess.run(
                cmd,
                cwd=cwd or self.path,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
                env={
                    "GIT_TERMINAL_PROMPT": "0",
                    "HOME": str(self.path.parent),
                    "PATH": "/usr/bin:/bin",
                },
            )
        except subprocess.TimeoutExpired as err:
            raise GitError(f"git {args[0]} timed out") from err
        if proc.returncode != 0:
            raise GitError(f"git {args[0]} failed: {proc.stderr.strip()[:500]}")
        return proc.stdout

    async def _git(self, *args: str) -> str:
        return await asyncio.to_thread(self._run, *args)

    def check_ref(self, ref: str) -> str:
        if not _REF_RE.match(ref) or ".." in ref.replace("...", ""):
            raise GitError(f"invalid ref {ref!r}")
        return ref

    def check_path(self, path: str) -> str:
        p = path.strip().lstrip("/")
        if ".." in Path(p).parts:
            raise GitPathNotAllowedError(f"path {path!r} escapes the repository")
        if self.allowed and not any(p == a.rstrip("/") or p.startswith(a) for a in self.allowed):
            raise GitPathNotAllowedError(f"path {path!r} is outside the allowed prefixes {list(self.allowed)}")
        return p

    async def ensure(self, *, force_fetch: bool = False) -> None:
        async with self._lock:
            if not (self.path / "HEAD").exists():
                self.path.parent.mkdir(parents=True, exist_ok=True)
                logger.info("cloning %s into %s", self.url, self.path)
                await asyncio.to_thread(
                    self._run,
                    "clone",
                    "--bare",
                    "--filter=blob:none",
                    self.url,
                    str(self.path),
                    cwd=self.path.parent,
                )
                self._last_fetch = time.time()
                return
            if force_fetch or time.time() - self._last_fetch > self.fetch_ttl:
                try:
                    await self._git("fetch", "--prune", "--quiet", "origin", "+refs/heads/*:refs/heads/*")
                    self._last_fetch = time.time()
                except GitError:
                    # Serve the last fetched state rather than failing reads;
                    # callers report freshness via status().
                    logger.warning("git fetch failed; serving cached clone", exc_info=True)

    # -------------------------------------------------------------- reads

    async def status(self) -> dict[str, Any]:
        await self.ensure()
        head = (await self._git("rev-parse", self.branch)).strip()
        return {
            "repo": self.url,
            "branch": self.branch,
            "head": head[:12],
            "last_fetch_age_s": round(time.time() - self._last_fetch, 1) if self._last_fetch else None,
            "note": "read-only clone; the agent never pushes to this branch",
        }

    async def log(
        self,
        path: str | None = None,
        *,
        limit: int = 20,
        since: str | None = None,
        until: str | None = None,
        ref: str | None = None,
    ) -> list[Commit]:
        await self.ensure()
        fmt = f"{_REC}%H{_SEP}%ct{_SEP}%an{_SEP}%s{_SEP}%b{_SEP}"
        args = ["log", f"--max-count={max(1, min(limit, 200))}", f"--format={fmt}", "--name-only"]
        if since:
            args.append(f"--since={since}")
        if until:
            args.append(f"--until={until}")
        args += ["--end-of-options", self.check_ref(ref or self.branch), "--"]
        args += [self.check_path(path)] if path else [a.rstrip("/") for a in self.allowed]
        out = await self._git(*args)
        commits = []
        for rec in out.split(_REC)[1:]:
            parts = rec.split(_SEP)
            if len(parts) < 6:
                continue
            files = [f for f in parts[5].strip().splitlines() if f]
            commits.append(Commit(parts[0], float(parts[1]), parts[2], parts[3], parts[4], files))
        return commits

    async def show(self, sha: str, *, max_chars: int = 20000) -> dict[str, Any]:
        await self.ensure()
        commits = await self.log(limit=1, ref=self.check_ref(sha))
        if not commits:
            raise GitError(f"no commit {sha} touching allowed paths")
        diff = await self._git(
            "show",
            "--format=",
            "--patch",
            "--end-of-options",
            self.check_ref(sha),
            "--",
            *[a.rstrip("/") for a in self.allowed],
        )
        return {"commit": commits[0].to_dict(with_body=True), "diff": _cap(diff, max_chars)}

    async def diff(self, base: str, head: str | None = None, path: str | None = None, *, max_chars: int = 20000) -> str:
        await self.ensure()
        refs = [self.check_ref(base)] + ([self.check_ref(head)] if head else [self.branch])
        paths = [self.check_path(path)] if path else [a.rstrip("/") for a in self.allowed]
        out = await self._git("diff", "--end-of-options", *refs, "--", *paths)
        return _cap(out, max_chars)

    async def blame(
        self, path: str, *, ref: str | None = None, start: int = 1, end: int | None = None
    ) -> list[dict[str, Any]]:
        await self.ensure()
        rev = self.check_ref(ref or self.branch)
        p = self.check_path(path)
        # blame errors on ranges past EOF, so clamp to the file length.
        total = len((await self.file_at(p, rev)).splitlines())
        first = min(max(1, start), max(total, 1))
        last = min(end if end else first + 59, total)
        # `git blame` rejects --end-of-options; check_ref already forbids a
        # leading '-', so the revision cannot be read as an option.
        out = await self._git("blame", "--line-porcelain", f"-L{first},{last}", rev, "--", p)
        rows: list[dict[str, Any]] = []
        cur: dict[str, Any] = {}
        for line in out.splitlines():
            if line.startswith("\t"):
                cur["text"] = line[1:]
                rows.append(cur)
                cur = {}
            elif re.match(r"^[0-9a-f]{40} ", line):
                sha, _orig, final = line.split()[:3]
                cur = {"sha": sha[:12], "line": int(final)}
            elif line.startswith("author "):
                cur["author"] = line[7:]
            elif line.startswith("author-time "):
                cur["date"] = time.strftime("%Y-%m-%d", time.gmtime(int(line[12:])))
            elif line.startswith("summary "):
                cur["summary"] = line[8:]
        return rows

    async def file_at(self, path: str, ref: str | None = None) -> str:
        await self.ensure()
        return await self._git("show", f"{self.check_ref(ref or self.branch)}:{self.check_path(path)}")

    async def seed_config(self, path: str, key: str = "printer.cfg", ref: str | None = None) -> str:
        """printer.cfg from a ConfigMap manifest at ref."""
        manifest = await self.file_at(path, ref)
        return extract_configmap_key(manifest, key)


def extract_configmap_key(manifest: str, key: str) -> str:
    for doc in yaml.safe_load_all(manifest):
        if isinstance(doc, dict) and doc.get("kind") == "ConfigMap":
            data = doc.get("data") or {}
            if key in data:
                return str(data[key])
    raise GitError(f"no ConfigMap with data key {key!r} in manifest")


def replace_configmap_key(manifest: str, key: str, new_value: str) -> str:
    """Replace a `key: |` block scalar in a ConfigMap manifest, textually.

    Keeps comments and formatting of everything else in the file. Only block
    scalars (`key: |`) are supported - that is how the homelab writes them.
    """
    lines = manifest.splitlines()
    pattern = re.compile(rf"^(?P<indent>\s*){re.escape(key)}:\s*\|[-+]?\s*$")
    for i, line in enumerate(lines):
        m = pattern.match(line)
        if not m:
            continue
        key_indent = len(m.group("indent"))
        j = i + 1
        body_indent: int | None = None
        while j < len(lines):
            cur = lines[j]
            if cur.strip():
                ind = len(cur) - len(cur.lstrip())
                if ind <= key_indent:
                    break
                if body_indent is None:
                    body_indent = ind
            j += 1
        # Trailing blank lines belong to the following content, not the block.
        while j > i + 1 and not lines[j - 1].strip():
            j -= 1
        pad = " " * (body_indent if body_indent is not None else key_indent + 2)
        body = [pad + ln if ln.strip() else "" for ln in new_value.rstrip("\n").split("\n")]
        new_lines = lines[: i + 1] + body + lines[j:]
        out = "\n".join(new_lines) + ("\n" if manifest.endswith("\n") else "")
        if extract_configmap_key(out, key).rstrip("\n") != new_value.rstrip("\n"):
            raise GitError("ConfigMap rewrite did not round-trip; refusing to produce it")
        return out
    raise GitError(f"no block scalar '{key}: |' found in manifest")


def _cap(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated {len(text) - limit} chars]"
