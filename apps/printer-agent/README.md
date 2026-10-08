# printer-agent

A kagent agent that operates the homelab's Klipper printers: it diagnoses
failures from evidence (Moonraker state, klippy.log, the running and on-disk
config, Git history, print history) and changes things only with approval.

- **Agent and deployment:** `k8s/prod/printer-agent/` (Argo CD app
  `printer-agent`).
- **MCP server source:** this directory, published as
  `ghcr.io/myoung34/printer-agent` by `.github/workflows/printer-agent.yaml`.
- **Docs:** [architecture](docs/architecture.md),
  [security model](docs/security.md), [runbook](docs/runbook.md),
  [example queries](docs/examples.md).

## Layout

| Module | Responsibility |
|---|---|
| `server.py` | MCP tool surface (39 tools), `/healthz`, `/metrics` |
| `service.py` | Gathers state from Moonraker, Kubernetes, and Git; records failures as data gaps |
| `diagnostics.py` | "What happened?", symptom workflows, readiness, failure history |
| `klippy_log.py` | klippy.log: sessions, wall-clock anchoring, Stats, shutdowns, G-code dump |
| `klipper_config.py` | Parse (incl. SAVE_CONFIG), validate, semantic diff with risk, minimal edits |
| `gcode.py` | Static G-code + embedded PrusaSlicer config analysis |
| `thermal.py` | Heater stability / fault analysis |
| `calibration.py` | Calibration state and ranked next steps |
| `taxonomy.py` | Failure classes, domains, log signatures (extensible via YAML) |
| `operations.py` | Gated writes with preconditions and verification |
| `remediation.py` | Propose → apply (backup, rollback) → PR to the Git seed |
| `safety.py` | Risk levels, policy, audit |
| `store.py` | SQLite: config versions, job outcomes, proposals, audit |
| `gitrepo.py` / `kube.py` | Read-only Git clone; read-only pod/event view |

## Develop

```bash
uv sync
uv run pytest            # ~4 s; simulated printer, no hardware needed
uv run ruff check src tests && uv run mypy src
```

`tests/sim.py` is a fake Moonraker with scenarios (`healthy`, `printing`,
`paused`, `mcu_disconnected`, `probe_failure`, `thermal_runaway`,
`config_error`, `cancelled`, offline). `tests/fixtures/` holds the real
printer configs from `k8s/prod/klipper`.
`tests/test_homelab_manifests.py` fails if the Agent's tool lists or the
inventory drift from the server.

## Adding a printer

1. Add it to `k8s/prod/klipper` as usual.
1. Add an entry to `k8s/prod/printer-agent/printers.yaml`.

No code change is needed.
