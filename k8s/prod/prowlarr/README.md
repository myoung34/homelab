Prowlarr
========

Indexer manager for the -arr stack. The design is documented in
`k8s/prod/rtorrent/README.md`.

Indexer searches must leave from the seedbox IP, the same IP rtorrent
announces from. Private trackers that see searches from home and announces
from the seedbox can treat it as account sharing.

## Prowlarr UI

- **Settings → General → Proxy**: enabled, type `HTTP(S)`, host
  `rtorrent.rtorrent.svc.cluster.local`, port `8888`, username and password
  from `HTTPPROXY_USER` / `HTTPPROXY_PASSWORD` in `secret/rtorrent`. Leave
  `Bypass Proxy for Local Addresses` on so Prowlarr still reaches Radarr
  directly.
- **Settings → Apps → + → Radarr**: Prowlarr server
  `http://prowlarr.prowlarr.svc.cluster.local:9696`, Radarr server
  `http://radarr.radarr.svc.cluster.local:7878`, plus Radarr's API key from
  Radarr's Settings → General.
- **Settings → Apps → + → Sonarr**: same, with Sonarr server
  `http://sonarr.sonarr.svc.cluster.local:8989` and Sonarr's API key.
- Re-add the indexers from the seedbox Prowlarr; its config is not migrated.
  Once they are in, stop the seedbox copy:
  `ssh seedbox tmux kill-session -t prowlarr`.
