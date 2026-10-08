# printer-agent architecture

An agent that operates the homelab's Klipper printers by reasoning over evidence
it actually retrieved: live Moonraker state, Klipper logs, the running and
on-disk configuration, Git history, and print history.

## What the homelab repo says (the constraints)

Everything below was discovered in `myoung34/homelab`, not assumed.

| Fact | Where | Consequence |
|---|---|---|
| Klipper + Moonraker run **in Kubernetes**, one Deployment per printer, namespace `klipper` | `k8s/prod/klipper/<printer>.yaml` | Moonraker is a ClusterIP Service: `http://<printer>.klipper.svc.cluster.local:7125`. No new networking needed. |
| The printers' MCUs are on USB in the Pi 5 node `klipper`, pinned via NFD per-serial labels | `nodefeaturerule.yaml`, `terraform/talos/locals.tf` | "Printer offline" may mean *pod unschedulable because the USB serial disappeared*. The agent reads pod state to tell these apart. |
| `printer.cfg` in Git is a **first-boot seed only**; the live file is on a Longhorn PVC and mutated by `SAVE_CONFIG` / Fluidd | `k8s/prod/klipper/README.md` | Git is not the runtime source of truth. **Drift (Git seed vs live file vs loaded config) is a first-class diagnostic.** Merging a seed change does not change the printer. |
| Moonraker `trusted_clients` covers `10.0.0.0/8` and `100.64.0.0/10`, no API key | `moonraker-configmap.yaml` | Every pod and every tailnet device can already command the printers. The agent's controls constrain the *agent*, not the network. |
| CNI is **flannel** (no NetworkPolicy enforcement) | `k8s/argo/configmap.yaml` comment, `terraform/talos` | NetworkPolicy would be decorative. Not shipped. |
| kagent **0.10.3**, API `kagent.dev/v1alpha2`; `McpServer` tools support `requireApproval` | `k8s/prod/kagent/kustomization.yaml`, CRD schema | Human-in-the-loop uses kagent's native approval rather than a home-grown one. |
| kagent's GitHub tools (via Aperture) cannot read file bodies | `k8s/prod/kagent/mcp.yaml` | Git access lives in the MCP server (a read-only clone of the public repo). |
| Observability is Datadog (all container logs collected); no Prometheus | `k8s/prod/datadog` | The server logs structured JSON (audit trail lands in Datadog for free) and exposes `/metrics` scraped by the Datadog OpenMetrics check via pod annotation. |
| Secrets: Vault → `VaultStaticSecret` + `VaultAuth`, `envFrom.secretRef` | every `vault.yaml` | The optional GitHub token for PR creation follows this. Nothing else needs a secret. |
| Custom images: `ghcr.io/myoung34/<name>:latest`, multi-arch | `http-to-mqtt` | Source lives in `apps/printer-agent/`; `.github/workflows/printer-agent.yaml` tests it on every push and publishes `ghcr.io/myoung34/printer-agent` from `main` only. |
| GitOps: ApplicationSet picks up `k8s/prod/*`; agents open PRs and never merge | `k8s/argo/appset.yaml`, `AGENTS.md` | New app dir `k8s/prod/printer-agent/`. Config PRs stop at "opened". |
| No cameras, MQTT, or Home Assistant printer integration exist | repo-wide search | Camera tool exists but reports "not configured" until a webcam is added in Moonraker. |
| PrusaSlicer profiles live in `myoung34/dotfiles`; every G-code embeds its slicer config | `dotfiles/home/dot_config/PrusaSlicer` | The G-code inspector reads the embedded `; prusaslicer_config` block. It doesn't need the profile files. |

## Components

```txt
                 kagent (namespace kagent)
  ┌──────────────────────────────────────────────────────┐
  │ Agent printer-agent  (Declarative, default-model-cfg)│
  │   tools:                                             │
  │    - RemoteMCPServer printer-mcp  (requireApproval   │
  │      on every write tool)                            │
  │    - kagent-tool-server: 4 read-only k8s tools       │
  │    - aperture: web_search / web_fetch only           │
  └───────────────┬──────────────────────────────────────┘
                  │ MCP streamable HTTP
                  ▼
  printer-mcp (namespace printer-agent, apps/printer-agent)
  ┌──────────────────────────────────────────────────────┐
  │ server.py      MCP tools, /healthz, /metrics          │
  │ safety.py      risk levels, policy, audit             │
  │ diagnostics.py evidence → timeline → hypotheses       │
  │ klippy_log.py  klippy.log parser (stats, shutdowns)   │
  │ klipper_config semantic parse, validate, diff, risk   │
  │ gcode.py       static G-code + slicer config analysis │
  │ calibration.py calibration state + next steps         │
  │ operations.py  gated writes with verification         │
  │ remediation.py propose → apply(+rollback) → PR        │
  │ gitrepo.py     read-only clone of myoung34/homelab    │
  │ kube.py        read-only pod/event view of `klipper`  │
  │ store.py       SQLite: config snapshots, jobs, audit  │
  │ poller.py      snapshots configs, records outcomes    │
  └──────┬─────────────────┬──────────────────┬──────────┘
         │                 │                  │
         ▼                 ▼                  ▼
   Moonraker (per     GitHub (clone;     kube-apiserver
   printer, klipper   PRs only if a      (get/list pods,
   namespace)         token is set)      events in klipper)
```

Inventory is a ConfigMap (`k8s/prod/printer-agent/printers.yaml`). Adding a printer
means adding an entry there. No code changes.

## Where each kind of state lives

| State | Store | Why |
|---|---|---|
| Printer inventory | Git (ConfigMap) | Config as code |
| Print history | Moonraker `[history]` (already on each printer's PVC) | Exists; not duplicated |
| Short-term temperature history | Moonraker `temperature_store` (20 min) and klippy.log `Stats` lines (~5 days of rotated logs) | Exists |
| Loaded-config history | klippy.log config dumps (backfill, ~5 days) + SQLite snapshots going forward | Klipper's logs rotate after 5 days. Known-good needs longer history. |
| Known-good / known-bad config | SQLite: config hash active at each job's start × job outcome | Derived. Nothing else holds it. |
| Audit of privileged actions | SQLite plus a structured log line (shipped to Datadog) | Queryable locally, and alertable in Datadog |
| Conversation history | kagent sessions (Postgres) | Exists |
| Seed config history | Git | Exists |

SQLite sits on a 1 GiB Longhorn volume declared the same way as the other apps
(`k8s/prod/longhorn/`), so it's covered by the existing recurring backup jobs.

## Diagnostic model

Every tool that interprets data returns findings with explicit certainty:

- `OBSERVED`: read directly from a source (log line, API field), with the
  source cited.
- `INFERRED`: follows deterministically from observations, such as "the
  shutdown happened during job 000123".
- `LIKELY` / `POSSIBLE`: hypotheses ranked by supporting and contradicting
  evidence.
- `UNKNOWN`: things that would change the conclusion but couldn't be
  determined. These are listed explicitly, and data sources that failed to load
  are listed as gaps.

Diagnosis has two layers on purpose. The **proximate cause** is what Klipper
reported, for example "verify_heater shut down the extruder". It's usually
`OBSERVED`. The **root-cause candidates** are what physically or
configurationally produces that report, for example "heater not delivering
power" vs "thermistor intermittent" vs "verify_heater too strict". Those are
ranked using the temperature trace, the config, other printers, and history.
Each candidate carries the least-invasive test that would discriminate it, along
with that test's risk level.

## Risk model

| Level | Examples | Gate |
|---|---|---|
| `READ_ONLY` | status, logs, config, git, history | none |
| `SAFE_AUTOMATION` | diagnose, compare, validate, propose a patch, `QUERY_PROBE` / `QUERY_ENDSTOPS` | refused while printing where it would send G-code |
| `LOW_RISK_WRITE` | restart Klipper, pause, set a heater to 0 | kagent approval + server policy |
| `HIGH_RISK_WRITE` | home, heat, start/cancel print, apply a config change of ordinary risk | kagent approval + server policy + preconditions |
| `DANGEROUS` | config changes touching thermal protection, temperature limits, MCU, pins, endstops/probe safety, kinematic limits | kagent approval + server policy (default **off**) + explicit per-change acknowledgement |

Not exposed at all: arbitrary G-code, shell, firmware flashing, file deletion,
history deletion, Kubernetes writes, secret reads.

The risk of a config change is computed from the semantic diff, not declared by
the caller.

## Config remediation flow (given the seed/PVC split)

```txt
diagnose ─▶ printer_config_propose(edits, rationale, evidence)
              │  structured section/option edits only; produces minimal diff,
              │  static validation, computed risk; stored as a proposal
              ▼
          human reviews diff in chat
              ▼
          printer_config_apply(proposal_id)          [requireApproval]
              │  base hash must still match live file; printer idle;
              │  backup → upload → RESTART → wait ready → verify the loaded
              │  config contains the new values; auto-rollback on failure
              ▼
          printer_config_open_pr(proposal_id)        [requireApproval]
                 applies the same edits to the Git seed ConfigMap, branch
                 printer-agent/<printer>-…, PR with evidence; never merges
```

After the operator merges, Argo CD syncs the seed. `printer_config_drift` then
confirms that Git, the live file, and the loaded config agree.

> [!IMPORTANT]
> Making Git authoritative for the live config would require changing the
> klipper Deployments: an init container that merges the seed with the PVC's
> `SAVE_CONFIG` block on every start, plus a controlled restart. A Reloader
> restart mid-print would kill the print. That is a design change to the
> `klipper` app and is deliberately **not** made here. See
> [the runbook](runbook.md#open-decisions).

## Phases

1. Read-only MVP: inventory, status, logs, config, git, history, health,
   failure classification, "what happened?".
2. Config intelligence: semantic analysis, validation, drift, known-good,
   calibration state, symptom workflows.
3. Controlled operations: restart, pause/resume/cancel, home, temperatures, and
   start print, each with approval, preconditions, and post-verification.
4. GitOps remediation: propose → apply with rollback → PR.
5. Deferred: camera analysis, anomaly detection, predictive maintenance. The
   camera tool is a stub until a webcam exists.

All four are implemented. The server-wide policy (`PRINTER_AGENT_MAX_RISK`) and
the per-printer `policy.max_risk` in `printers.yaml` decide which ones are live.
Both are set in Git.
