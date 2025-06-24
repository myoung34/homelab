Talos
=====

Notes
=====

* This will not run on GHA because I dont trust it enough to not leak stdout for certs/secrets
* to reset a node to bootstrap: `talosctl reset --system-labels-to-wipe EPHEMERAL,STATE --reboot --graceful=false --wait=false -n 192.168.x.y`
* to find the network prefix: `talosctl -e 192.168.1.22 -n 192.168.1.22 get links --insecure` and look for an `ether` likely without a type
