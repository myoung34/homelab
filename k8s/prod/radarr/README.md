Radarr
======

Radarr imports from rtorrent's downloads into the NAS library. The design,
Vault setup and seedbox relay are documented in `k8s/prod/rtorrent/README.md`.

Radarr's own traffic (TMDB, metadata) goes out directly from home. Only
rtorrent and Prowlarr leave through the seedbox.

## Radarr UI

Radarr's config lives in its SQLite DB on the `radarr-config` PVC, so these
are click-ops, not GitOps.

### Settings → Media Management

- Root folder: `/media/movies`
- Use Hardlinks instead of Copy: **on**. Downloads and library share one NFS
  mount, so imports cost no space and torrents keep seeding.

### Settings → Download Clients → + → rTorrent

| field     | value                                    |
|-----------|------------------------------------------|
| Host      | `rtorrent.rtorrent.svc.cluster.local`    |
| Port      | `8000`                                   |
| Use SSL   | off                                      |
| URL Path  | `RPC2`                                   |
| Username  | `radarr`                                 |
| Password  | the `HTPASSWD` password from Vault setup |
| Category  | `radarr`                                 |
| Directory | blank                                    |

`Category` is load-bearing: rtorrent moves finished torrents to
`/media/torrents/complete/<category>/`. Leave `Directory` blank so new
downloads land in `/media/torrents/temp/`. rtorrent and Radarr mount the share
at the same path, so no remote path mapping is needed.
