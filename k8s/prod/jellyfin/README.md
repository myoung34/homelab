Jellyfin
========

Media server on cluster41, reading the NAS share `/volume1/Media` read-only
at `/media`. Replaced Plex, whose off-network playback needs a paid pass.

- **Public / tailnet:** `https://media.king-gila.ts.net` (Tailscale Funnel).
- **LAN without Tailscale (TVs):** `https://media.marcyoung.us`, via traefik
  on the Cilium LB VIP `192.168.1.50` (`lan-ingress.yaml`). Not
  `media.king-gila.ts.net`: off-tailnet that name goes out through Funnel
  at a few Mbit/s.
- **Transcoding:** CPU only. Both GPUs on cluster41 are allocated to ollama.

| Library  | Folder          |
|----------|-----------------|
| Movies   | `/media/movies` |
| TV Shows | `/media/tv`     |

Don't add `/media/torrents/`: Radarr and Sonarr hardlink finished
downloads into `movies/` and `tv/`, so everything would show twice.

## First-time setup

Jellyfin's startup wizard is unauthenticated until it completes, and Funnel
makes it public, so finish it immediately after the first deploy. The admin
password lives in Vault at `secret/jellyfin` (`ADMIN_USER`, `ADMIN_PASSWORD`).

Radarr and Sonarr notify Jellyfin on import (Settings → Connect → Emby /
Jellyfin, host `jellyfin.jellyfin.svc.cluster.local`, port `8096`, API key
from Jellyfin's Dashboard → API Keys).

## Gotchas

- **Prefers cluster41**, but can run elsewhere if it's down (CPU
  transcoding on an arm64 board will be slow).
- **No UDP discovery**: without hostNetwork, clients add the server by URL.
- **Config is on Longhorn** (`jellyfin-config`, 20 Gi, nightly backup).
