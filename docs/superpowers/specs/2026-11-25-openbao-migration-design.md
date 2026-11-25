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
| 21 k8s roles | live config (`coder` retired 2026-11-25: delete its role and policy before export) |

`nomad/openbao-bootstrap.sh` copies all of the above: `export` reads the old
Vault into a 0700 dir, `import` writes it to OpenBao (refuses unless the
target is raft-backed, so it can't hit the old file-backed Vault), `verify`
diffs every KV path.

### Cutover

0. One-time NAS prep (container runs as uid 100, gid 1000):
   ```sh
   sudo install -d -o 100 -g 1000 -m 700 /volume1/openbao /volume1/@appdata/openbao
   sudo openssl rand -out /volume1/@appdata/openbao/unseal-20261125-1.key 32
   sudo chown 100:1000 /volume1/@appdata/openbao/unseal-20261125-1.key
   sudo chmod 400 /volume1/@appdata/openbao/unseal-20261125-1.key
   ```
   Copy the key to the password manager.
1. Delete the `coder` k8s role and policy from Vault, then
   `nomad/openbao-bootstrap.sh export <dir>` against Vault.
2. Stop the `vault` job, then `nomad job run nomad/openbao.hcl`.
3. `bao operator init -recovery-shares=1 -recovery-threshold=1` (static seal
   yields recovery keys, not unseal keys). Store the recovery key and root
   token offline.
4. `nomad/openbao-bootstrap.sh import <dir>` with the new root token (ends
   with `verify`). Run without direnv overriding `VAULT_ADDR`.
5. Verify (below), then remove `nomad/vault.hcl` and update the README's
   Vault lines.

Rollback: stop `openbao`, start `vault` (data untouched), unseal by hand.

### Verification

- Restart the `openbao` alloc: it comes back `sealed=false` with no input.
- Every exported KV path hash-matches its source.
- A Nomad job restart (e.g. `obsidian`) renders its template.
- Every `VaultStaticSecret` reports synced; force one with a reloader-watched
  app.
- Datadog vault check stays green.

## Builder findings (tested locally against 2.7.3)

- Image runs as `openbao` uid 100 / gid 1000; data dir and key must be
  owned by it or raft fails with `permission denied` on `vault.db`.
- `api_addr = http://192.168.3.2:8200`, `cluster_addr = http://127.0.0.1:8201`.
- Static seal: restart comes back `Sealed false` with no input.
- `jwt` and `kubernetes` auth are built in. OpenBao accepted Nomad's
  `oidc_discovery_url` (fetched live). A kubernetes login with a real
  cluster SA token passed TokenReview and read KV v2 with the issued
  `s.` token, which is the flow VSO uses.
- `bao operator raft snapshot save` works.
- `/v1/sys/health` answers as Vault's does (Datadog check).
- Still untested: a Nomad workload-identity login (needs a live job);
  covered by the obsidian restart in Verification.
