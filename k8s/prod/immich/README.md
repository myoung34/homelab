# immich

Self-hosted photo and video library (web UI + mobile app backup). The library
lives on the NAS; if the cluster dies the photos survive.

## Stack

| piece          | where                          | notes                                |
|----------------|--------------------------------|--------------------------------------|
| immich-server  | k8s, this namespace            | v3.4.2, port 2283                    |
| redis          | k8s, this namespace            | ephemeral cache/queue                |
| Postgres       | Synology `192.168.3.2:5432/immich` | creds from Vault, key `DB_URL` |
| photo library  | Synology NFS `/media/photos`   | mounted at `/data`, the write target |

## Access

- **Tailnet only:** `https://immich.king-gila.ts.net`
- **Mobile app:** Immich (iOS/Android), server URL above
- No Funnel, no public exposure

## One-time setup before first deploy works

1. On the Synology Postgres:
   ```sql
   CREATE USER immich PASSWORD '...';
   CREATE DATABASE immich OWNER immich;
   -- in the immich database, install the vector extension and set
   -- DB_VECTOR_EXTENSION in immich.yaml to match (vectorchord by default):
   CREATE EXTENSION vectorchord;
   ```
2. `vault kv put secret/immich DB_URL="postgresql://immich:PASSWORD@192.168.3.2:5432/immich" # pragma: allowlist secret`
3. k8s Vault role `immich` allowing the `default` service account in namespace
   `immich` to read `secret/immich` (pattern: `k8s/prod/paperless-ngx/vault.yaml`)
4. Make sure `/media/photos` exists and is exported (it is on the same share
   as `/volume1/Media`; create a subfolder and add it to the export list if
   not present).

ArgoCD picks the app up automatically (ApplicationSet git generator over
`k8s/prod/*`); the pod will not come up until the Vault secret exists.

## Not in this PR (deliberate)

- **immich-machine-learning** - face recognition, smart search and ML
  thumbnails are off. The server tolerates the missing service. Add it later
  if wanted; it needs a GPU or real CPU and a model cache volume.
- **Postgres backup** - the `immich` DB is on the Synology and is not in the
  `k8s/prod/workflows/psql-*` CronWorkflow set. Add one if you want it covered
  by the MinIO backup path.

## Notes

- Image tag is pinned `v3.4.2` (current release at the time of writing).
  Bump it through Renovate rather than hand-editing, per repo convention.
- Node affinity prefers `cluster41` (amd64, real CPU); the Pi 4s (ARMv8.0)
  will SIGILL on arm64 images built for ARMv8.1+, so it should land on
  cluster41 or a Pi 5.
