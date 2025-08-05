Talos
=====

Notes
=====

* This will not run on GHA because I dont trust it enough to not leak stdout for certs/secrets
* to reset a node to bootstrap: `talosctl reset --system-labels-to-wipe EPHEMERAL,STATE --reboot --graceful=false --wait=false -n 192.168.x.y`
* to find the network prefix: `talosctl -e 192.168.1.22 -n 192.168.1.22 get links --insecure` and look for an `ether` likely without a type

To upgrade:

```
$ curl -X POST --data-binary @bare-metal.yaml https://factory.talos.dev/schematics
{"id":"b8e8fbbe1b520989e6c52c8dc8303070cb42095997e76e812fa8892393e1d176"}

$ talosctl upgrade --nodes 192.168.1.19,192.168.1.24 --image factory.talos.dev/metal-installer/b8e8fbbe1b520989e6c52c8dc8303070cb42095997e76e812fa8892393e1d176:v1.10.6

$ curl -X POST --data-binary @pi.yaml https://factory.talos.dev/schematics
{"id":"9992b4ade979cf2fc812e6f07e264d1f240d11b0d1eb795ce78771f8647a316"}

$ talosctl upgrade --nodes 192.168.1.21,192.168.1.22,192.168.1.23,192.168.1.25,192.168.1.26 --image factory.talos.dev/metal-installer/9992b4ade979cf2fc812e6f07e264d1f240d11b0d1eb795ce78771f8647a316:v1.10.6
```
