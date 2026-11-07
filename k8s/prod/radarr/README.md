Radarr
======

Radarr runs here, rtorrent stays on the seedbox, the library lives on the NAS.

```
                 k8s (arm64)                      seedbox                NAS
  ┌──────────────────────────────────┐       ┌───────────────┐    ┌──────────────┐
  │ radarr ──► localhost:10050 ──────┼─ssh──►│ lighttpd      │    │              │
  │            (autossh -L)          │       │   :10050      │    │              │
  │                                  │       │   ruTorrent   │    │              │
  │                                  │       │     httprpc   │    │              │
  │                                  │       │       │       │    │              │
  │                                  │       │   rtorrent ──►│    │              │
  │                                  │       │   ~/data/     │    │              │
  │                                  │       │     radarr/   │    │              │
  │                                  │       └───────┬───────┘    │              │
  │ prowlarr ─► localhost:1080 ──────┼─ssh──►  (SOCKS5 out)       │              │
  └──────────────────────────────────┘               │            │              │
                                                     │ rsync      │              │
                        seedbox-sync CronWorkflow ───┴───────────►│ /volume1/    │
                        (k8s/prod/workflows/)                     │   Movies/    │
                                                                  │   .downloads │
  radarr ──────────── NFS 192.168.3.2:/volume1/Movies ───────────►│              │
                                                                  └──────────────┘
```

Why it is shaped this way:

* rtorrent's SCGI is a **unix socket** (`~/.rtorrent.socket`), not a TCP port,
  so there is nothing for Radarr to dial directly. ruTorrent's `httprpc`
  plugin is the only XMLRPC-over-HTTP surface, and the per-user lighttpd that
  serves it (`server.port = 10050`, config at `~/.lighttpd.conf`) sits behind
  htpasswd. The `seedbox-tunnel` sidecar forwards that port into the pod, so
  nothing on the seedbox has to be reachable from the internet except sshd.
* Prowlarr's tunnel is `-D` (SOCKS5) instead, because what it needs is for
  *outbound* indexer traffic to leave from the seedbox IP — trackers that see
  the announce from the seedbox and the search from a home IP get unhappy.
* `/volume1/Movies/.downloads` is the rsync landing dir, deliberately on the
  same NFS export as the library so an import is a hardlink and not a
  20 GB copy. Radarr skips dot-directories, so it stays out of the library.

## First time set up

### 1. Seedbox key (operator, once)

Generate a dedicated keypair and authorise it on the seedbox:

```
ssh-keygen -t ed25519 -N '' -C 'radarr@k8s' -f /tmp/seedbox-k8s
ssh-copy-id -i /tmp/seedbox-k8s.pub seedbox
```

Put the **private** key in all three Vault paths (the two apps and the
workflow namespace each read their own secret):

```
vault kv patch secret/radarr   SEEDBOX_SSH_KEY=@/tmp/seedbox-k8s
vault kv patch secret/prowlarr SEEDBOX_SSH_KEY=@/tmp/seedbox-k8s
vault kv patch secret/argowf   SEEDBOX_SSH_KEY=@/tmp/seedbox-k8s
shred -u /tmp/seedbox-k8s /tmp/seedbox-k8s.pub
```

Vault kubernetes auth roles `radarr` and `prowlarr` need to exist and be bound
to the `default` service account in their own namespaces, the same as every
other app here.

### 2. NFS export (operator, once)

DSM → Control Panel → Shared Folder → `Movies` → Edit → NFS Permissions. The
cluster subnet needs `rw`, `async`, **squash: no mapping** (or map to
`myoung`/`users`). `PUID=1026` / `PGID=100` in the Deployment matches the
existing ownership of `/volume1/Movies`.

### 3. Radarr UI

Radarr's config lives in its SQLite DB on the `radarr-config` PVC, so these
are click-ops, not GitOps.

**Settings → Media Management**

* Root folder: `/movies`
* Use Hardlinks instead of Copy: **on** — the `seedbox-sync` workflow runs
  `rsync --delete`, so the library copy must be a hardlink that survives the
  landing copy being reaped.

**Settings → Download Clients → + → rTorrent (ruTorrent)**

| field       | value                                                 |
|-------------|-------------------------------------------------------|
| Host        | `localhost`                                           |
| Port        | `10050`                                               |
| Use SSL     | off (the ssh tunnel is the encryption)                |
| URL Path    | `user-vilpengu/rutorrent/plugins/httprpc/action.php`  |
| Username    | `vilpengu`                                            |
| Password    | seedbox panel password                                |
| Directory   | `/home/vilpengu/data/radarr`                          |

`Directory` is load bearing: it is what keeps Radarr's downloads in the one
subdirectory `seedbox-sync` mirrors, instead of mixed into the other 360 GB
already sitting in `~/data`.

**Settings → Download Clients → Remote Path Mappings → +**

| field       | value                          |
|-------------|--------------------------------|
| Host        | `localhost`                    |
| Remote Path | `/home/vilpengu/data/radarr/`  |
| Local Path  | `/movies/.downloads/`          |

### 4. Prowlarr UI

* **Settings → General → Proxy**: enabled, type `Socks5`, host `localhost`,
  port `1080`, no credentials.
* **Settings → Apps → + → Radarr**: Prowlarr server
  `http://prowlarr.prowlarr.svc.cluster.local:9696`, Radarr server
  `http://radarr.radarr.svc.cluster.local:7878`, plus Radarr's API key from
  Settings → General.
* Re-add the indexers from the seedbox Prowlarr
  (`https://lt5-1-87vecchio.pulsedmedia.com/public-vilpengu/prowlarr/`); its
  config is not migrated. Once they are in, stop the seedbox copy:
  `ssh seedbox tmux kill-session -t prowlarr`.

## Gotchas

* **Import race.** rtorrent has no move-on-complete hook, so a torrent can
  finish between two `seedbox-sync` runs and Radarr can try to import a file
  rsync has not finished updating. `--partial-dir` stops Radarr seeing a
  *truncated* file, but a file that was copied while incomplete and has not
  been re-synced yet will look whole. Radarr retries on its next cycle. The
  real fix is a `method.set_key = event.download.finished` hook in
  `~/.rtorrent.rc.custom` on the seedbox moving completed data into
  `~/data/radarr/complete/`; not done because it needs an rtorrent restart.
* **First sync is slow.** Nothing is in `~/data/radarr` yet, so the first runs
  are no-ops, but once downloads start a 20 GB remux takes more than the
  15 minute schedule. `concurrencyPolicy: Forbid` means overlapping runs are
  skipped rather than stacked.
* **The tunnel sidecars `apk add` at startup.** No registry mirror for
  `openssh-client`/`autossh` means a pod restart during a Docker Hub outage
  leaves Radarr running with no download client. Same tradeoff the
  `workflows/` jobs already make.
* **Host key is pinned inline** in `radarr.yaml`, `prowlarr.yaml`, and
  `seedbox-sync.yaml`. PulsedMedia rebuilding the box rotates it and all three
  break at once with `Host key verification failed`.
* **All cluster nodes are arm64.** `lscr.io/linuxserver/*` publishes arm64v8,
  so no nodeAffinity is needed — unlike paperless-ngx, which pins arch for its
  own reasons.
