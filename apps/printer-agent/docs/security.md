# printer-agent security model

The agent is privileged automation that can move hardware and heat it, so it
is constrained at every layer it touches. Where a control isn't enforced, this
document says so.

## Threat model in one paragraph

The model's output drives tool calls, so treat it as untrusted. A confused or
manipulated agent must not be able to heat or move a printer without a human
approving that exact call. It must not weaken safety systems unless the change
is approved, explicitly acknowledged, and allowed by a policy set in Git. It
must not gain shell, arbitrary G-code, cluster write, secret access or Git push
to `main`.

## Controls

| Layer | Control |
|---|---|
| Tool surface | 39 narrow tools. No shell, no arbitrary G-code, no raw moves, no firmware flashing, no file or history deletion. |
| Human approval | kagent `requireApproval` on all 10 write tools (`k8s/prod/printer-agent/agent.yaml`). A test fails if a write tool is added without it. |
| Server policy | `PRINTER_AGENT_MAX_RISK` (deployment) and `policy.max_risk` per printer (`printers.yaml`). The lower one wins. Shipped at `HIGH_RISK_WRITE`, so DANGEROUS changes are refused until both are raised in a reviewed commit. |
| Computed risk | Config change risk comes from the semantic diff, not from the caller. Every DANGEROUS change must be named in `acknowledge_dangerous`. |
| Preconditions | No restart, homing, heating, probe query or config apply while printing. Heater targets are capped at min(policy cap, `max_temp` - 10 °C). A print starts only if readiness passes and the G-code has no error-level findings (unless acknowledged). |
| Verification | Results are `verified: true` only when the printer is read back in the expected state. A config apply rolls back automatically if Klipper doesn't return ready. |
| Concurrency | A config apply is refused if `printer.cfg` changed since the proposal (hash check). |
| Git | Read-only clone of the public repo. Ref validation, path allowlist (`k8s/prod/klipper`, `k8s/prod/printer-agent`). PRs only, on `printer-agent/*` branches; the code refuses the default branch and never merges. The token is optional and should be fine-grained to this repo. |
| Kubernetes | The ServiceAccount can `get/list` pods and events in `klipper` only. The agent's own k8s tools are the 4 read-only ones (and kagent-tool-server is bound read-only). |
| Secrets | Only `GITHUB_TOKEN`, from Vault (`secret/printer-agent`) via VaultStaticSecret. It isn't mounted for reads elsewhere, and the agent has no secret read tool. |
| Pod | PodSecurity `restricted`: non-root uid 10001, read-only root filesystem, all capabilities dropped, seccomp RuntimeDefault. |
| Audit | Every privileged attempt (requested, denied, precondition_failed, verified, failed) goes to SQLite and is logged as JSON, which Datadog collects. It's queryable with `printer_audit_log` and counted as `printer_agent_actions_total`. |

## Known gaps (not fixed here, by design or out of scope)

> [!WARNING]
> **Moonraker is open to the whole cluster and tailnet.**
> `moonraker-configmap.yaml` trusts `10.0.0.0/8` and `100.64.0.0/10` with no
> API key, and the CNI is flannel, so NetworkPolicy isn't enforced. Any pod or
> tailnet device can already command the printers directly. The controls above
> constrain the *agent*; they don't secure the printers. Closing this means
> Moonraker API keys (the inventory supports `api_key_env`) plus narrower
> `trusted_clients`, which would also affect Fluidd. That's a separate change.

- **No authentication on printer-mcp.** Any pod can call it. It's no worse than
  calling Moonraker directly (see above), but a bearer token via
  RemoteMCPServer `headersFrom` would be the next step.
- **Thermal protection is weakened today on every printer.**
  `[verify_heater extruder] max_error: 12000000`, `hysteresis: 50` in all three
  seeds. The agent reports it as `danger`, but changing it is DANGEROUS-tier
  and stays with you.
- **Approval is in kagent's UI.** If kagent's approval flow were bypassed, the
  server policy and preconditions still apply, but no human would see the call.
