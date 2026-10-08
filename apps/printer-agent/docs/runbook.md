# printer-agent runbook

## First deployment

1. Merge the PR. Argo CD creates the `printer-agent` app (ApplicationSet picks
   up `k8s/prod/printer-agent`), and the workflow publishes the image.
1. **Make the GHCR package public, once.** A new package published from the
   homelab repo is private by default, and the cluster pulls without
   credentials. Until then the pod sits in `ImagePullBackOff`. (Alternative: an
   image pull secret from Vault.)
1. Optional, for PRs from the agent: create a fine-grained GitHub token
   (myoung34/homelab: contents + pull requests, read/write) and:

   ```bash
   vault kv put secret/printer-agent GITHUB_TOKEN=...
   # plus a Vault kubernetes-auth role `printer-agent` bound to
   # SA printer-agent in namespace printer-agent, policy read on
   # secret/data/printer-agent - same shape as the other apps' roles.
   ```

   Without it, everything works except `printer_config_open_pr`.

## Health checks

```bash
kubectl -n printer-agent get pods
kubectl -n printer-agent logs deploy/printer-agent | tail
kubectl -n kagent get agent printer-agent remotemcpserver printer-mcp
kubectl -n printer-agent port-forward svc/printer-mcp 8080 &
curl -s localhost:8080/healthz; curl -s localhost:8080/metrics | grep printer_online
```

In Datadog, metrics are under `printer.*` (OpenMetrics check via pod
annotation) and logs are in `service:printer-agent`. Lines starting with
`audit` are privileged actions.

## Symptoms

| Symptom | Check |
|---|---|
| Agent says a tool server is unavailable | `kubectl -n kagent describe remotemcpserver printer-mcp`; the pod must be Ready. |
| `printer_unreachable` for a printer | `printer_status` includes pod state. A Pending pod with an affinity mismatch means the printer's MCU isn't on USB (off, unplugged, not enumerating). |
| Git tools fail | The clone lives in `/data/homelab.git`. It needs egress to github.com. A stale clone keeps serving reads; `last_fetch_age_s` in `printer_git_log` shows its age. |
| History says "no config record" for old jobs | Expected. Config history starts when the agent first ran, plus ~5 days backfilled from klippy.log. |
| A write returns `policy_denied` | Working as intended. Raise `PRINTER_AGENT_MAX_RISK` / `policy.max_risk` in Git if you really mean to. |
| A config apply failed and rolled back | The result names the backup: `config/printer-agent-backups/printer-<time>-<sha>.cfg` on the printer (visible in Fluidd). Klipper is back on the previous file. |

## Recover a printer config by hand

Backups are in the printer's `config/printer-agent-backups/`. In Fluidd, copy
one over `printer.cfg` and `RESTART`. `printer_config_history` lists the
recorded versions, and `printer_config_get source=snapshot:<sha>` returns any
of them.

## State

`/data/printer-agent.sqlite` is on the Longhorn volume `printer-agent-data`,
which is backed up by the existing recurring jobs. Losing it loses config
history and the audit log, and nothing else; the agent rebuilds from Moonraker
and klippy.log.

## Open decisions

- **Git as the live source of truth for `printer.cfg`.** Today the ConfigMap is
  a first-boot seed. Making Git authoritative means changing the klipper
  Deployments: an init container that merges the seed with the volume's
  `SAVE_CONFIG` block on every start, plus a restart that never fires
  mid-print (a Reloader restart would kill a print). Until then the agent
  applies to the live file and opens a PR to keep the seed in step.
- **Moonraker auth.** See [security](security.md#known-gaps-not-fixed-here-by-design-or-out-of-scope).
- **OpenTelemetry tracing.** kagent supports it, but the Datadog agent here
  doesn't have OTLP ingest enabled. Enabling it is a change to the datadog and
  kagent apps.
