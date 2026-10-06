# AGENTS.md

## Mandate: GitOps only — never apply changes by hand

This cluster is driven by **ArgoCD** (`k8s/argo/appset.yaml`), with
`automated.prune: true` and `selfHeal: true` against `HEAD` of
`https://github.com/myoung34/homelab`. Git is the only source of truth.

Rules, in order:

1. **Never** run `kubectl apply`, `kubectl edit`, `kubectl patch`,
   `kubectl scale`, `helm install/upgrade`, or any other mutating command
   against the cluster. ArgoCD `selfHeal` reverts it within minutes
   anyway, so a manual change is both a policy break and a lie that
   disappears.
1. Make the change as a **file edit** in this repo, then ship it as a
   **pull request** — branch, commit, push, `gh pr create`, and stop
   there. Never commit or push to `main`, and never merge your own PR:
   ArgoCD tracks `HEAD` of `main`, so the merge *is* the deploy, and
   that call belongs to the operator.
1. Any cluster-mutating action, including one-off ones, needs **explicit
   operator approval first** — ask, show exactly what you intend to run,
   and wait.
1. Read-only inspection is always fine: `kubectl get/describe/logs`,
   `kubectl exec` for read-only commands, `argocd app diff`.

Irreversible data operations (DB deletes, `manage.py` mutations, PVC
changes) are *not* covered by "it's just a one-off" — they need the same
explicit approval, even though they live outside ArgoCD's reconciliation.

## WHY

Personal homelab: a Talos Kubernetes cluster plus a Synology running
Nomad, with secrets in Vault, backups in MinIO, and networking through
Tailscale/Unifi. See `README.md` for the topology, hardware notes, and
the network diagram.

## WHAT

```
k8s/argo      ArgoCD itself + the ApplicationSet that generates all apps
k8s/prod/*    One directory per app; each is an ArgoCD Application
k8s/stage     Staging manifests
talos         Encrypted Talos machine configs + kubeconfig/talosconfig
terraform     unifi, talos, tailscale, cloudflare
nomad         Jobs that run on the Synology
misc          No rule here
```

Key conventions in `k8s/prod/<app>/`:

- `kustomization.yaml` lists the manifests and sets `namespace`.
- Secrets come from Vault via `vault.yaml`
  (`VaultStaticSecret` + `VaultAuth`), consumed with `envFrom.secretRef`.
  Never put a literal secret in a manifest.
- `secret.reloader.stakater.com/reload` annotations restart workloads on
  secret rotation.
- `tailscale.yaml` exposes the service on the tailnet.
- Scheduled jobs (e.g. Postgres backups to MinIO) are Argo
  `CronWorkflow`s in `k8s/prod/workflows/`.
- Image versions are bumped by Renovate (`renovate.json`), not by hand.

Adding an app = a new `k8s/prod/<name>/` directory; the ApplicationSet
git generator picks it up automatically.

## HOW

```bash
direnv allow           # exports KUBECONFIG/TALOSCONFIG/VAULT_ADDR/NOMAD_ADDR
pre-commit run -a      # the only test suite (also CI, .github/workflows/test.yaml)
kubectl kustomize k8s/prod/<app>   # render locally to validate, mutates nothing
```

`pre-commit` runs `check-yaml`, whitespace/EOF fixers,
`detect-private-key`, and `detect-secrets` against `.secrets.baseline`.
Run it before handing a diff over for review.

### Gotchas

- `.envrc` points `KUBECONFIG` at `talos/kubeconfig`, so a shell outside
  this repo (or without direnv) talks to no cluster — or the wrong one.
- ArgoCD uses `ServerSideApply=true`. Client-side `kubectl apply` on
  these resources silently drops newly added list entries (observed with
  `env` entries on a Deployment), which is one more reason not to apply
  by hand.
- The tailscale operator owns `spec.externalName` on egress Services;
  see the long comment in `k8s/argo/appset.yaml` before touching
  `ignoreDifferences`.
- Some manifests are excluded from `check-yaml` (tailscale charts,
  esphome devices, hass config) — see `.pre-commit-config.yaml`.
