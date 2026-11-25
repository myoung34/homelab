# Replace Vault with OpenBao (static auto-unseal, Raft)

## Why

Vault on the Synology uses a 1-of-1 Shamir seal. Every NAS reboot leaves it
sealed until someone unseals it by hand, and every Nomad job and VSO-synced
k8s Secret stalls until then (incident 2026-11-25). Open-source Vault only
auto-unseals via cloud KMS or a second Vault (Transit). OpenBao ships a
`static` seal that auto-unseals from a local key file, with no cloud
dependency.

## Goals

- Secrets service on the NAS comes back unsealed after a reboot with no human
  step.
- Same address (`http://192.168.3.2:8200`) and API, so Nomad, VSO, Datadog
  and the CLI need no client changes.
- Built-in, consistent backups (`bao operator raft snapshot save`).

## Non-goals

- HA or multi-node.
- TLS on the listener (unchanged from today).
- Scheduling Raft snapshots to MinIO (follow-up).
- Moving VSO to External Secrets Operator.

## Anti-goals

- Unseal key present in any backup, shared folder, Nomad job spec, or
  container env. That would make every backup a plaintext secret dump.
- A cutover with no rollback path.

## Constraints

- Single Synology node, Docker via Nomad, `/volume1` on spinning disk.
- Postgres reads its admin creds from this service
  (`nomad/postgresql.hcl:29-30`), so it cannot be the storage backend.
- OpenBao 2.7 removed `file` storage; the tested in-place path starts from
  Vault 1.14.1 and this Vault is 1.13.3.
- VSO is not officially supported against OpenBao; it relies on API
  compatibility (unverified).

## Approaches

| # | Approach | Trade-off |
|---|---|---|
| 1 | **Fresh OpenBao 2.7 + Raft + static seal, reload from exports** | Few steps, no storage-compat risk. All tokens and 40 auto-created identity entities are lost; clients re-auth. |
| 2 | In-place: Vault 1.14 → OpenBao 2.6 (file) → migrate storage → 2.7 → seal migrate | Keeps tokens/identity. Five fallible steps, one untested (1.13 data). |

**Picked: 1.** Data is small (27 KV paths, 24 policies, 2 auth mounts) and
already exported and hash-verified against live Vault.

Storage: **Raft** over PebbleDB (no snapshot command, pitched for
"single server or local dev") and PostgreSQL (circular dependency above).

## Design

### Runtime

- New Nomad job `nomad/openbao.hcl`, image `quay.io/openbao/openbao:2.7.x`
  (Renovate-pinned), static port 8200, data at `/volume1/openbao`
  (new dir; `/volume1/vault` stays untouched for rollback).
- Config:
  - `storage "raft"` with `path` and `node_id`; `api_addr` /
    `cluster_addr` set explicitly.
  - `seal "static"` with `current_key = "file://..."` and a dated
    `current_key_id`.
  - No `disable_mlock` (removed in OpenBao 2.0).
- Unseal key: 32 random bytes at `/volume1/@appdata/openbao/unseal.key`,
  outside every shared folder, mode 0400, owned by the container's uid,
  bind-mounted read-only. Offline copy in the password manager.

### State to recreate

Sources are the 2026-11-25 exports plus live config read before cutover.

| What | Source |
|---|---|
| KV v2 at `secret/` (27 paths) | `vault-backup-20261125-0849.json` |
| 24 policies | `vault-policies-20261125-0851.json` |
| `jwt-nomad/` auth: `oidc_discovery_url` + `bound_issuer` = `http://192.168.3.2:4646` | live config |
| jwt role `nomad-cluster`: aud `vault.io`, `user_claim=nomad_job_id`, policies `nomad-server` | live config |
| token role `nomad-cluster`: allowed `nomad-server`, orphan, renewable, period 72h | live config |
| `kubernetes/` auth: host `https://192.168.1.254:6443`, cluster CA, reviewer JWT from secret `vault-secrets-operator/vault-auth-token` | live config + k8s |
| 22 k8s roles | 21 via `nomad/restore-vault-acl.sh`; `coder` (SA `default`, ns `coder`, policy `coder`) by hand |

Commit the recreate steps as a script (`nomad/openbao-bootstrap.sh`) so the
next rebuild is one command.

### Cutover

1. Re-export KV and policies immediately before cutover; diff against the
   2026-11-25 files.
2. Stop the `vault` job, then start `openbao`.
3. `bao operator init` (static seal yields recovery keys, not unseal keys).
   Store the recovery key and root token offline.
4. Run the bootstrap script.
5. Verify (below), then remove `nomad/vault.hcl`.

Rollback: stop `openbao`, start `vault` (data untouched), unseal by hand.

### Verification

- Restart the `openbao` alloc: it comes back `sealed=false` with no input.
- Every exported KV path hash-matches its source.
- A Nomad job restart (e.g. `obsidian`) renders its template.
- Every `VaultStaticSecret` reports synced; force one with a reloader-watched
  app.
- Datadog vault check stays green.

## Left to the builder

- Container uid for key-file ownership; exact `api_addr` / `cluster_addr`.
- Whether Nomad's Vault client accepts OpenBao's version string (2.x);
  test in step 5 before deleting the old job.
- Confirm `jwt` and `kubernetes` auth are built into the OpenBao 2.7 image.
- Update the README line "Vault … Backed by Minio" (already stale).
