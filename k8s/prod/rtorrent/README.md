rtorrent
========

rtorrent, Radarr and Prowlarr run in the cluster, and the library lives on the
NAS. The seedbox is only the exit node: everything rtorrent and Prowlarr send
to the internet leaves from its IP, and peers reach rtorrent through it.

```txt
 internet ⇄ seedbox 185.148.1.87
   egress:  PulsedMedia wireguard, NAT out of the seedbox IP
   ingress: :47123 rtorrent-relay (systemd --user) ──► 10.90.90.155:47123
                      ▲ wireguard tunnel
 k8s ─────────────────┼─────────────────────────────────────────────────
  rtorrent pod: [gluetun: wg + kill-switch + :8888 proxy] + rtorrent/ruTorrent
  prowlarr ──► rtorrent:8888 (proxy)    radarr ──► rtorrent:8000 (XMLRPC)
  rtorrent + radarr ──► NFS 192.168.3.2:/volume1/Media mounted at /media
```

Why it is shaped this way:

- **Egress.** PulsedMedia gives each account a wireguard profile
  (`~/wireguard.txt`) whose traffic exits from the seedbox IP. gluetun runs it
  as a native sidecar, and its firewall drops anything that is not the tunnel.
  If the tunnel goes down, traffic stops; it never falls back to the home
  connection.
- **Ingress.** That wireguard does no inbound port forwarding. A small TCP relay
  on the seedbox listens on the public `:47123` and dials the pod's fixed
  tunnel address. Peers see the seedbox; the pod sees every inbound peer as
  `10.90.90.1`, which rtorrent accepts. Trackers are told `185.148.1.87:47123`
  via `WAN_IP` and `RT_INC_PORT`.
- **One key, one tunnel.** The Deployment is `Recreate` because two pods with
  the same key would fight over the peer.
- **Storage.** Downloads (`/media/torrents/`) and the library
  (`/media/movies/`) are one NFS mount at the same path in rtorrent and Radarr.
  Imports are hardlinks, and Radarr needs no remote path mapping. Config and
  session state stay on Longhorn: the NAS only speaks NFSv3 and the mount is
  `nolock`, which SQLite does not survive.

## First-time setup

### 1. Vault

```bash
PW=$(openssl rand -hex 16)
vault kv put secret/rtorrent \
  WIREGUARD_PRIVATE_KEY="$(ssh seedbox "awk -F' = ' '/^PrivateKey/{print \$2}' ~/wireguard.txt")" \
  HTPASSWD="$(htpasswd -nbB radarr "$PW")" \
  HTTPPROXY_USER=prowlarr \
  HTTPPROXY_PASSWORD="$(openssl rand -hex 16)"
echo "radarr XMLRPC/ruTorrent password: $PW"
```

`HTPASSWD` guards XMLRPC, ruTorrent and WebDAV. XMLRPC can run arbitrary
commands, and flannel enforces no NetworkPolicy, so it is not optional.

Create the policy and kubernetes auth role from `vault.yaml`:

```bash
cd k8s/prod/rtorrent && ../../../nomad/restore-vault-acl.sh
```

### 2. Seedbox relay

The unit and script live in `seedbox/`:

```bash
ssh seedbox 'mkdir -p ~/bin ~/.config/systemd/user'
scp seedbox/rtorrent-relay.py seedbox:bin/
scp seedbox/rtorrent-relay.service seedbox:.config/systemd/user/
ssh seedbox 'systemctl --user daemon-reload && systemctl --user enable --now rtorrent-relay'
```

PMSS already enables lingering for the account (rootless Docker runs the same
way), so the unit survives logout and reboot.

### 3. NAS

`/volume1/Media` is its own shared folder, exported read/write to
`192.168.1.0/24`. It has to be a single shared folder: on Btrfs each shared
folder is a subvolume, and hardlinks cannot cross subvolumes.

### 4. Retire the seedbox rtorrent

Its torrents are not migrated. Stop it from the PMSS panel, or
`ssh seedbox pkill -u vilpengu rtorrent`; PMSS's watchdog restarts it unless it
is disabled in the panel.

## Gotchas

- **MTU is 1390, not the 1420 in `wireguard.txt`.** Flannel's pod MTU is 1450
  and wireguard over IPv4 adds 60 bytes. At 1420 every full packet fragments,
  and single-stream throughput drops from about 13 MB/s to 5 MB/s.
- **IPv6 is blocked in rtorrent.** The tunnel carries IPv4 only, so dual-stack
  trackers time out on AAAA without `network.block.ipv6.set`.
- **`files/.rtorrent.rc` is a copy of the image's template** plus the lines
  above. The `seed-config` init container copies it over the PVC copy on every
  start, so edits in ruTorrent's settings do not persist. Re-check it against
  `/tpls/.rtorrent.rc` when Renovate bumps the image.
- **The image `chown`s and `chmod`s `/passwd` and `.rtorrent.rc` at startup and
  dies if that fails.** That is why both are copied into writable volumes
  instead of being mounted read-only.
- **gluetun's control server is bound to `127.0.0.1`.** It is unauthenticated,
  and `PUT /v1/vpn/status` stops the tunnel.
- **The tunnel address `10.90.90.155` is assigned by PMSS** and appears in
  `rtorrent.yaml` and `seedbox/rtorrent-relay.service`. If PulsedMedia
  regenerates the key, update `wireguard.txt`, Vault, and both files.
- **The NFS mount is `hard`.** If the NAS goes away, rtorrent and Radarr block
  until it comes back instead of erroring.
