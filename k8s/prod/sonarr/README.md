Sonarr
======

Sonarr is Radarr for TV. It imports from rtorrent's downloads into the NAS
library. The design, Vault setup and seedbox relay are documented in
`k8s/prod/rtorrent/README.md`.

Sonarr's own traffic (TVDB, metadata) goes out directly from home. Only
rtorrent and Prowlarr leave through the seedbox.

## Sonarr UI

Sonarr's config lives in its SQLite DB on the `sonarr-config` PVC, so these
are click-ops, not GitOps.

### Settings → Media Management

- Root folder: `/media/tv`
- Use Hardlinks instead of Copy: **on**. Downloads and library share one NFS
  mount, so imports cost no space and torrents keep seeding.

### Settings → Download Clients → + → rTorrent

Same as Radarr's, except the category:

| field     | value                                    |
|-----------|------------------------------------------|
| Host      | `rtorrent.rtorrent.svc.cluster.local`    |
| Port      | `8000`                                   |
| Use SSL   | off                                      |
| URL Path  | `RPC2`                                   |
| Username  | `radarr`                                 |
| Password  | the `HTPASSWD` password from Vault setup |
| Category  | `sonarr`                                 |
| Directory | blank                                    |

`Category` is load-bearing: rtorrent moves finished torrents to
`/media/torrents/complete/<category>/`. A category separate from Radarr's
keeps each app from importing the other's downloads.

### Settings → Connect → + → Emby / Jellyfin

Host `jellyfin.jellyfin.svc.cluster.local`, port `8096`, API key from
Jellyfin's Dashboard → API Keys.
