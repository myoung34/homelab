Jellyfin
========

Media server on cluster41, reading the NAS share `/volume1/Media` read-only
at `/media`. Replaced Plex, whose off-network playback needs a paid pass.

- **Public / tailnet:** `https://media.king-gila.ts.net` (Tailscale Funnel).
- **LAN:** `hostNetwork`, so `http://192.168.1.32:8096`.
- **Transcoding:** CPU only. Both GPUs on cluster41 are allocated to ollama.

| Library  | Folder          |
|----------|-----------------|
| Movies   | `/media/movies` |
| TV Shows | `/media/tv`     |

Don't add `/media/torrents/`: Radarr hardlinks finished downloads into
`movies/`, so every movie would show twice.

## First-time setup

Jellyfin's startup wizard is unauthenticated until it completes, and Funnel
makes it public, so finish it immediately after the first deploy. The admin
password lives in Vault at `secret/jellyfin` (`ADMIN_USER`, `ADMIN_PASSWORD`).

Radarr notifies Jellyfin on import (Settings → Connect → Emby / Jellyfin,
host `jellyfin.jellyfin.svc.cluster.local`, port `8096`, API key from
Jellyfin's Dashboard → API Keys).

## Gotchas

- **cluster41 is a single point of failure.** The pod is pinned there.
- **Config is on Longhorn** (`jellyfin-config`, 20 Gi, nightly backup).
