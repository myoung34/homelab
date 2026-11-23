# immich

Self-hosted photo and video library (web UI + mobile app backup). The library
lives on the NAS; if the cluster dies the photos survive.

## Stack

| piece          | where                          | notes                                |
|----------------|--------------------------------|--------------------------------------|
| immich-server  | k8s, this namespace            | v3.4.2, port 2283                    |
| immich-ml      | k8s, this namespace            | v3.4.2, port 3003, face/CLIP/OCR     |
| redis          | k8s, this namespace            | ephemeral cache/queue                |
| Postgres       | Synology `192.168.3.2:5432/immich` | creds from Vault, key `DB_URL` |
| photo library  | Synology NFS `/volume1/Media/photos` | mounted at `/data`, the write target |
| ML model cache | Longhorn (`longhorn-1r`, 20Gi) | `/cache`, models are re-downloadable |

## Access

- **Tailnet only:** `https://immich.king-gila.ts.net`
- **Mobile app:** Immich (iOS/Android), server URL above
- No Funnel, no public exposure

## One-time setup (done 2026-11-23, outside git)

1. Postgres: the Synology job runs immich's PG16 image with pgvector and
   VectorChord and preloads `vchord.so` (`nomad/postgresql.hcl`). In it:
   ```sql
   CREATE ROLE immich LOGIN PASSWORD '...';
   CREATE DATABASE immich OWNER immich;
   \c immich
   CREATE EXTENSION vchord CASCADE;        -- pulls in vector
   CREATE EXTENSION earthdistance CASCADE; -- pulls in cube
   ```
   immich is not a superuser, so after a VectorChord upgrade run
   `ALTER EXTENSION vchord UPDATE; REINDEX INDEX face_index; REINDEX INDEX clip_index;`
   by hand (immich docs, administration/postgres-standalone.md).
2. `vault kv put secret/immich DB_URL="postgresql://immich:PASSWORD@192.168.3.2:5432/immich" # pragma: allowlist secret`
3. Vault policy and k8s role `immich` (`default` service account, namespace
   `immich`, read `secret/immich`).
4. `/volume1/Media/photos` exists on the NAS (under the `/volume1/Media`
   export jellyfin/radarr/rtorrent use).

ArgoCD picks the app up automatically (ApplicationSet git generator over
`k8s/prod/*`); nothing else is needed before merge.

## Not in this PR (deliberate)

- **Postgres backup** - the `immich` DB is on the Synology and is not in the
  `k8s/prod/workflows/psql-*` CronWorkflow set. Add one if you want it covered
  by the MinIO backup path.

## Notes

- Image tags are pinned `v3.4.2` (current release at the time of writing),
  server and machine-learning together so the two stay compatible. Bump them
  through Renovate rather than hand-editing, per repo convention.
- Node affinity: the server **prefers** `cluster41` (amd64, real CPU); the
  machine-learning pod **requires** it - the inference work is CPU-bound and
  slow on a Pi, and cluster41 is the only amd64 node with real CPU. The Pi 4s
  (ARMv8.0) will SIGILL on arm64 images built for ARMv8.1+.
- Face recognition / smart search / OCR run in the ML service, pointed at the
  server via `IMMICH_MACHINE_LEARNING_URL` (port 3003, `/ping` health, models
  cached at `/cache`).
