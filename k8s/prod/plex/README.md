Plex
====

Plex Media Server on cluster41, reading the NAS share `/volume1/Media`
read-only at `/media`.

- **LAN:** `hostNetwork`, so clients find it by discovery or at
  `http://192.168.1.32:32400/web`.
- **Tailnet:** `https://plex.king-gila.ts.net` via `tailscale.yaml`.
- **Transcoding:** CPU only. Both GPUs on cluster41 are allocated to ollama.

## First-time setup

A new server has to be claimed from a local address. Port-forward so the
request comes from `127.0.0.1`:

```bash
kubectl -n plex port-forward deploy/plex 32400:32400
```

Open `http://localhost:32400/web`, sign in, and name the server.

Add libraries:

| Library  | Folder          |
|----------|-----------------|
| Movies   | `/media/movies` |
| TV Shows | `/media/tv`     |

Don't add `/media/torrents/`: Radarr hardlinks finished downloads into
`movies/`, so every movie would show twice.

## Gotchas

- **cluster41 is a single point of failure.** The pod is pinned there; when
  the node reboots, Plex is down until it's back.
- **Config is on Longhorn** (`plex-config`, 20 Gi, nightly backup). Metadata
  and thumbnails grow with the library.
