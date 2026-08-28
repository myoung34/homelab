Syncthing
=========

Pulls finished media off the remote seedbox and lands it on bigNASty.

```
  seedbox (remote, internet)                 k8s cluster              bigNASty
  ~/data/complete/Movies  --[ BEP over ]-->  syncthing  --[ NFS ]-->  /volume1/Movies
  ~/data/complete/TV         tailnet         (this app)   v4.1        /volume1/TV
```

The seedbox joins the tailnet and dials `syncthing-sync.king-gila.ts.net:22000`.
No port forward on the UDM, and no falling back to Syncthing's public relays,
which are bandwidth-throttled and would be painful at movie sizes.

GUI: <https://syncthing.king-gila.ts.net>

## Heads up: Syncthing on NFS is a known rough edge

This runs Syncthing against NFS-mounted folders, which the upstream project and
community consistently warn about — spurious rescans, phantom "file changed"
events, out-of-sync churn, and permission failures creating `.stfolder`. The
manifests mitigate the ones that are mitigable:

* the index database lives on Longhorn, never on NFS (see `pvc.yaml`)
* no `fsGroup`, so the kubelet never recursively chowns the library
* the filesystem watcher must be **off** on the NFS folders (see below) —
  inotify does not propagate over NFS, so it does nothing but cost churn

The alternative that sidesteps all of it is running Syncthing as a Nomad job on
bigNASty with `/volume1` bind-mounted locally, the way `nomad/obsidian.hcl`
does. Worth revisiting if this proves flaky.

## Synology prep

Do this **before** first sync or the pod will not start — a missing export
means the NFS mount fails and the pod never becomes ready.

1. Both shared folders already exist (`Movies` and `TV` are both present on the
   NAS). Nothing to create.
2. NFS itself is **already enabled** and needs no change — `rpcinfo -p
   192.168.3.2` shows rpcbind, mountd, nfs and nlockmgr registered. Note it
   registers nfs versions **2 and 3 only**, so NFSv4 is off; `nfs.yaml` mounts
   v3 accordingly. If you ever turn on NFSv4.1 under Control Panel → File
   Services → NFS → Advanced, update `mountOptions` to match.
3. Export rules are **done** — `showmount -e 192.168.3.2` lists both
   `/volume1/Movies` and `/volume1/TV` to `192.168.1.0/24`.

   One change worth making: set Squash to **"Map root to admin"** (root squash).
   A probe pod running as uid 0 currently gets full read/write on the library,
   because "No mapping" trusts whatever uid the client asserts — and AUTH_SYS
   verifies nothing. Syncthing runs as uid 1026 and never needs root on these
   mounts (the only root step is the init container, which touches the Longhorn
   config volume, not NFS), so root squash costs nothing here.

4. **The Permissions tab does not apply to NFS.** This is the trap. Shared
   Folder → Edit → **Permissions** (the user/group Read/Write grid) governs
   SMB, AFP, FTP and File Station. NFS ignores it entirely — access is decided
   by the export rule plus the raw numeric uid/gid checked against the
   filesystem.

   Measured, not assumed: with `syncthing` and `myoung` both showing Read/Write
   in that tab, a pod as uid 1026 still gets `READ_DENIED` and `WRITE_DENIED` on
   both shares, while uid 0 gets full access. Granting more accounts in that
   grid will not change it.

   **The fix in use: Squash → "Map all users to admin"** on the
   `192.168.1.0/24` rule (Shared Folder → Edit → NFS Permissions → Edit). Every
   incoming uid maps to admin regardless of what it claims, so access no longer
   depends on `runAsUser`.

   Verified by A/B — with the change applied to `Movies` but not yet `TV`, the
   same pod as uid 1026 got `READ_OK`/`WRITE_OK` on Movies and
   `DENIED`/`DENIED` on TV. The squash setting was the only difference.

   Tradeoff, accepted knowingly: anything on `192.168.1.0/24` that mounts these
   shares now acts as admin. That is not a regression — under "No mapping" a
   client could simply assert uid 0 and get true superuser, which a probe
   confirmed. Squashing to admin removes the superuser bypass. The export ACL
   remains the real boundary either way, which is why it must stay scoped to
   the cluster subnet.

   The alternative, if you ever want per-identity control instead: grant the uid
   at the filesystem level over SSH. The share root is `root:root` reporting
   `0777`, which is a synthesised mode — the Synology ACL underneath is the real
   gate.

   ```
   id syncthing
   synoacltool -get /volume1/Movies
   ```

5. `runAsUser` is now cosmetic for NFS. With all uids squashed to admin, files
   land owned by admin no matter what the pod claims. The value still matters
   for the Longhorn config volume, which the init container chowns — so leave
   it set.

   Re-run the probe in Troubleshooting and confirm `WRITE_OK` on **both** shares
   before pointing Syncthing at these mounts.

## How auth works over NFS (mostly, it doesn't)

Worth being explicit, because it is the weakest link in this design.

NFS here runs with `sec=sys` (AUTH_SYS), which is **not authentication**. The
client simply asserts a numeric uid and gid in every RPC and the server takes
its word for it. There is no password, no token, no key exchange. `runAsUser:
1026` in the Deployment is not a credential — it is an unverified claim, and
anything that can reach port 2049 from a permitted address can make the same
claim.

So the actual access control is entirely network-level, and it is two things:

1. **The export ACL** — the `192.168.1.0/24` rule from the Synology prep above.
   This is the real security boundary. Anything on the cluster VLAN can mount
   these shares and read/write the library as any uid it likes.
2. **VLAN separation** — the NAS lives on VLAN 3 and only the cluster VLAN is
   permitted to mount.

Consequences worth accepting knowingly:

* Any pod that can get a host mount, and any device that lands on
  `192.168.1.0/24`, can reach the library. Keep the export scoped to the
  cluster subnet — never `*` or a whole-LAN supernet.
* "Squash: No mapping" is what lets uid 1026 come through as uid 1026. Root
  squash would break `.stfolder` creation, but it is also the only thing
  limiting a rogue client claiming uid 0. Scoping the export is what carries
  the weight here, not the squash setting.
* Nothing about this is encrypted in flight. It is cleartext on the wire
  between the cluster and the NAS.

The only real authentication option for NFS is Kerberos (`sec=krb5` /
`krb5i` / `krb5p`). Synology supports it for NFSv4, but it needs a KDC,
principals and a keytab on every client — and the Talos kubelet has no
`gssd`, so it is not practically reachable here. Not recommended; noted so the
tradeoff is a decision rather than an oversight.

The Syncthing link itself is unrelated and genuinely authenticated: BEP is TLS
with mutual device-ID pinning, carried over WireGuard on the tailnet. The soft
spot is only the cluster-to-NAS hop.

## How the two ends find each other

Three separate layers, worth keeping distinct:

**Identity — device IDs.** Every Syncthing instance generates a TLS keypair on
first start; the device ID is a hash of that certificate. You paste each side's
ID into the other. Connections are mutually authenticated TLS, so a device
whose ID you have not added cannot connect, and nobody can impersonate one
without the private key. This is genuine cryptographic authentication — unlike
the NFS hop, which authenticates nothing.

**Addressing — how it finds an IP:port.** Syncthing has four mechanisms:

| Mechanism | Useful here? |
| --------- | ------------ |
| Local discovery (multicast, 21027/udp) | No — LAN only, the seedbox is remote |
| Global discovery (`discovery.syncthing.net`) | Works, but leaks announcements publicly |
| Static configured address | **Yes — what we use** |
| Relay (`relays.syncthing.net`) | Fallback only; throttled, painful at movie sizes |

**Direction — who dials whom.** The cluster is the listener: the
`tailscale.com/expose` Service in `tailscale.yaml` publishes port 22000 as its
own tailnet node. The seedbox dials in. Only one side has to successfully
connect, so:

* On the **seedbox**, add the cluster device with a static address:
  `tcp://syncthing-sync.king-gila.ts.net:22000`
* On the **cluster**, add the seedbox device and leave its address `dynamic` —
  it only ever accepts.

Then, on both sides, turn **off** global discovery and relaying (Actions →
Settings → Connections). With static addressing they are redundant, and leaving
relaying on means a transient tailnet problem silently downgrades you to a
throttled public relay instead of failing loudly.

### Tailnet ACL — this will not work out of the box

`terraform/tailscale/acl.tf` is default-deny. The only rule that would let a
seedbox reach `tag:k8s` is the blanket `*:*` grant for `autogroup:admin`,
`tag:admin-device`, `tag:k8s` and `tag:k8s-operator`.

Do **not** solve this by tagging the seedbox `tag:admin-device`. That hands a
remote, internet-exposed box that runs a torrent client unrestricted access to
every node on your tailnet. Give it its own tag scoped to just this port:

```hcl
"tagOwners": {
  "tag:seedbox": [],
},

"acls": [
  {
    "action": "accept",
    "src":    ["tag:seedbox"],
    "dst":    ["tag:k8s:22000"],
  },
],
```

Then enrol the seedbox with an auth key tagged `tag:seedbox`. It can reach the
Syncthing transport port and nothing else.

## First-time setup

Folder and device config is runtime state in `config.xml` on the Longhorn PVC,
not in git. The manifests bring up the process; the pairing below is manual and
done once. It survives pod restarts.

### 1. Get the cluster device ID

```
kubectl -n syncthing exec deploy/syncthing -- syncthing device-id
```

(`device-id` is a subcommand in v2, not the `--device-id` flag v1 used.)

### 2. Seedbox side (Pulsed Media)

PM shared seedboxes (V/M/Dragon-R series) are Debian VMs under Proxmox with a
plain user account — **no root, no sudo** — and files under `/home/<user>/`.
That rules out a normal Tailscale install (no access to `/dev/net/tun`) and
rules out systemd units. Everything below runs in userspace.

**Check these first:**

```
ssh <user>@<host>
which syncthing tailscale tailscaled
ls ~/data/complete/
```

Syncthing has historically shipped preinstalled on PMSS, but confirm rather than
assume — the source for that is old. And **ask PM support whether running
`tailscaled` is acceptable on your plan** before doing it. A VPN daemon on a
shared box is exactly the sort of thing that can breach ToS, and it is your
account at risk, not mine.

#### Connectivity — pick one

**Option A: Tailscale in userspace mode.** Keeps everything on the tailnet, no
public exposure. `tailscaled` runs as a SOCKS5 proxy instead of creating a
tunnel device, so it needs no root:

```
mkdir -p ~/bin ~/.tailscale
# grab the current static amd64 tarball from pkgs.tailscale.com/stable/
curl -fsSL https://pkgs.tailscale.com/stable/tailscale_<VER>_amd64.tgz | tar xzf -
mv tailscale_*/tailscale tailscale_*/tailscaled ~/bin/

~/bin/tailscaled --tun=userspace-networking \
                 --socks5-server=localhost:1055 \
                 --outbound-http-proxy-listen=localhost:1055 \
                 --statedir=$HOME/.tailscale \
                 --socket=$HOME/.tailscale/tailscaled.sock &

~/bin/tailscale --socket=$HOME/.tailscale/tailscaled.sock up \
                --hostname=seedbox \
                --advertise-tags=tag:seedbox
```

**`--socket` is not optional.** `tailscaled` defaults it to
`/var/run/tailscale/tailscaled.sock`, which an unprivileged user cannot create —
omitting it fails with:

```
safesocket.Listen: listen unix /var/run/tailscale/tailscaled.sock: bind: no such file or directory
```

The same applies to **every** `tailscale` CLI invocation, not just `up`. Without
it the CLI goes looking for the default root-owned socket and cannot find the
daemon. Save yourself the repetition:

```
alias tailscale='~/bin/tailscale --socket=$HOME/.tailscale/tailscaled.sock'
```

`--statedir` alone is sufficient for state — the state file lands at
`<statedir>/tailscaled.state` when `--state` is unset. `--port` defaults to 0
(kernel picks a free UDP port), which is what you want unless PM restricts
outbound UDP to specific ports.

#### The auth key

The key goes on `tailscale up` — **never** on `tailscaled`, which has no concept
of it. Order matters, because the tag has to exist before a key can reference
it:

1. Apply the `tag:seedbox` ACL change in `terraform/tailscale/acl.tf` first.
2. Generate the key at <https://login.tailscale.com/admin/settings/keys> →
   Generate auth key → tick **Tags** → `tag:seedbox`. Make it **single-use** and
   short-expiry; it is consumed the moment the seedbox registers, so a copy left
   in your shell history is already spent.
3. Use it once:

```
~/bin/tailscale --socket=$HOME/.tailscale/tailscaled.sock up \
                --auth-key=tskey-auth-... \
                --hostname=seedbox \
                --advertise-tags=tag:seedbox
```

Why a key rather than interactive login: `tag:seedbox` will have empty
`tagOwners` (matching the existing style in `acl.tf`), and an empty list means no
ordinary user can apply that tag interactively. Tailnet Owners/Admins can apply
any tag regardless, so as tailnet admin browser login would also work — but a
tagged key is the standard route for a headless box and avoids the browser
round-trip entirely.

Gotcha: re-running `tailscale up` later fails with *"changing settings via
'tailscale up' requires mentioning all non-default flags"*. Either restate
`--advertise-tags=tag:seedbox` every time or pass `--reset`.

Note `--auth-key` is not documented as supporting the `file:` prefix that
`--client-secret` and `--id-token` accept — do not assume it does. A single-use
key is the better mitigation.

Then run Syncthing pointed at that proxy:

```
export ALL_PROXY=socks5://localhost:1055
syncthing serve --home=$HOME/.config/syncthing
```

Two consequences of proxying, both fine here:

* **Outbound only.** Syncthing behind a SOCKS5 proxy cannot accept incoming
  connections. This is precisely why the cluster is the listener and the
  seedbox dials it — the topology was chosen for this.
* **TCP only.** QUIC over SOCKS5 is not documented as working, so address the
  cluster as `tcp://`, not `quic://`.

**Option B: public port instead of a VPN daemon.** If PM will not allow
`tailscaled`, forward a port on the UDM to the cluster's Syncthing and have the
seedbox dial it directly over the internet. BEP is TLS with device-ID pinning
and is designed to be internet-facing, so this is a legitimate choice rather
than a hack — the cost is one publicly reachable port, and the `tailscale.com/
expose` Service in `tailscale.yaml` gets replaced by a LoadBalancer or NodePort.

#### Keeping it running

No systemd, so run each daemon in its own named tmux session. Start them by
hand:

```
tmux new-session -d -s tailscaled \
  '$HOME/bin/tailscaled --tun=userspace-networking --socks5-server=localhost:1055 --outbound-http-proxy-listen=localhost:1055 --statedir=$HOME/.tailscale --socket=$HOME/.tailscale/tailscaled.sock 2>&1 | tee -a $HOME/tailscaled.log'

tmux new-session -d -s syncthing \
  'ALL_PROXY=socks5://localhost:1055 syncthing serve --home=$HOME/.config/syncthing 2>&1 | tee -a $HOME/syncthing.log'
```

Then `tmux attach -t tailscaled` to watch it, `Ctrl-b d` to detach, `tmux ls` to
list, `tmux kill-session -t tailscaled` to stop. Piping through `tee` matters:
without it the session dies with the process and you lose the reason.

tmux does **not** survive a reboot, so back it with the same command in cron.
Using `has-session` keeps one mechanism rather than two, and avoids a `pgrep`
watchdog racing a session you started by hand:

```
*/5 * * * * tmux has-session -t tailscaled 2>/dev/null || tmux new-session -d -s tailscaled '$HOME/bin/tailscaled --tun=userspace-networking --socks5-server=localhost:1055 --outbound-http-proxy-listen=localhost:1055 --statedir=$HOME/.tailscale --socket=$HOME/.tailscale/tailscaled.sock 2>&1 | tee -a $HOME/tailscaled.log'
*/5 * * * * tmux has-session -t syncthing 2>/dev/null || tmux new-session -d -s syncthing 'ALL_PROXY=socks5://localhost:1055 syncthing serve --home=$HOME/.config/syncthing 2>&1 | tee -a $HOME/syncthing.log'
```

When the process exits, the session goes with it, `has-session` fails, and cron
restarts it within five minutes.

If `systemctl --user` works on your box, a user unit with `Restart=always` is
tidier — but it needs `loginctl enable-linger $USER` to survive logout, which
usually requires privileges you do not have here. Try it; fall back to tmux.

#### Reaching the seedbox GUI

It binds to localhost. Tunnel to it rather than exposing it:

```
ssh -L 8384:localhost:8384 <user>@<host>
```

Then open <http://localhost:8384>.

#### Folders

Add two folders:

| Path                      | Folder ID | Folder Type | Watcher |
| ------------------------- | --------- | ----------- | ------- |
| `~/data/complete/Movies`  | `movies`  | Send Only   | On      |
| `~/data/complete/TV`      | `tv`      | Send Only   | On      |

Folder IDs must match exactly on both sides or the share will not link. Labels
can differ. Add the cluster device ID as a remote device and share both folders
with it.

Two separate folders, deliberately — syncing `complete/` as one folder would
nest everything under a single destination instead of splitting into
`/volume1/Movies` and `/volume1/TV`.

### 3. Cluster side

In the GUI, accept the two shares and set:

| Folder ID | Path                     | Folder Type  | Watcher |
| --------- | ------------------------ | ------------ | ------- |
| `movies`  | `/var/syncthing/Movies`  | Receive Only | **Off** |
| `tv`      | `/var/syncthing/TV`      | Receive Only | **Off** |

Turn the watcher **off** on both and leave the periodic rescan on (default
3600s). inotify does not work over NFS, so the watcher only generates noise.

Set a GUI username and password under Actions → Settings. The tailnet gets you
transport encryption and device authentication, but the GUI has no auth of its
own until you set one.

## Deletes: decide before you prune the seedbox

Default above (plain Receive Only) **mirrors** deletions — prune a movie off the
seedbox to reclaim space and it disappears from `/volume1/Movies` too. If you
want the NAS to be an archive that outlives the seedbox copy, set `ignoreDelete`
on the two receiving folders (Settings → Advanced → Folders → select folder):

* Incoming deletions are discarded; the NAS keeps the file.
* Cost: the folders will read as permanently "out of sync" in the UI, because
  each side legitimately considers the other behind. This is cosmetic, and a
  long-standing complaint upstream.
* **Never press "Override changes" on the seedbox.** It bypasses `ignoreDelete`
  and has caused data loss for people relying on it.

Middle ground: leave deletes propagating but enable staggered file versioning on
the receiving folders, so removed files land in `.stversions` on volume1 and age
out. Costs disk.

## Troubleshooting

**Probe the mount without touching Syncthing** — Fastest way to test uid/ACL
changes in isolation. Runs as the same identity the real Deployment uses:

```
kubectl run nfs-probe --rm -it --restart=Never --image=busybox:1.37 \
  --overrides='{"spec":{"securityContext":{"runAsUser":1026,"runAsGroup":100,"supplementalGroups":[100]},
  "volumes":[{"name":"m","nfs":{"server":"192.168.3.2","path":"/volume1/Movies"}}],
  "containers":[{"name":"p","image":"busybox:1.37","stdin":true,"tty":true,
  "volumeMounts":[{"name":"m","mountPath":"/mnt"}]}]}}' -- sh
```

Then inside: `id`, `ls -ln /mnt`, `touch /mnt/.probe`. Change `runAsUser` to
test a different account. Note `ls | head` masks the exit code — check for a
`Permission denied` on stderr rather than trusting `&&`.

**`access denied by server` at mount time** — Export rule problem, not
credentials. Confirm with `showmount -e 192.168.3.2`; both shares should list
against `192.168.1.0/24`. A host outside that range is refused here, which is
the whole access-control model.

**Mount succeeds but reads/writes are `Permission denied`** — The export let you
in; the filesystem is refusing you. Expect `drwxrwxrwx root:root`, which is a
synthesised mode and tells you nothing useful. Do **not** reach for the
Permissions tab — it does not apply to NFS. See step 4: either squash to admin,
or grant the uid via `synoacltool`. Confirm with the probe, testing uid 0 as a
control — if root works and your uid does not, it is a filesystem/ACL problem,
not an export problem.

**`mount.nfs` helper not found after a Talos upgrade** — The NFS client ships
inside the kubelet image rather than the OS, so kubelet patch bumps have broken
mounts before. Suspect the kubelet version, not this config.

**Folder stuck at "Permission denied" / cannot create `.stfolder`** — uid/gid
mismatch or the export is squashing. Re-check steps 3 and 4 above.

**Everything shows as owned by `nobody:nobody` (65534)** — Should not happen on
v3, which is numeric-only with no idmapping. If it appears, the export is
squashing (check that the rule is set to "No mapping") or someone enabled NFSv4
without an `idmapd` on the Talos side.

**Folder shows "out of sync" forever** — expected if `ignoreDelete` is on. If it
is not, look for local modifications on the receiving side; Receive Only folders
surface those as an override prompt rather than silently reverting.
