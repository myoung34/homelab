Talos
=====

Notes
=====

* This will not run on GHA because I dont trust it enough to not leak stdout for certs/secrets
* to reset a node to bootstrap: `talosctl reset --system-labels-to-wipe EPHEMERAL,STATE --reboot --graceful=false --wait=false -n 192.168.x.y`
* to find the network prefix: `talosctl -e 192.168.1.22 -n 192.168.1.22 get links --insecure` and look for an `ether` likely without a type

To start over:
```
$ export _node=192.168.1.x
$ talosctl reset -e ${_node} -n ${_node} --graceful=false --system-labels-to-wipe STATE --system-labels-to-wipe EPHEMERAL --reboot
$ # wait for all to show 'unknown authority'
$ terraform apply \
  -target='talos_machine_configuration_apply.controlplane["192.168.1.22"]' \
  -target='talos_machine_configuration_apply.controlplane["192.168.1.25"]' \
  -target='talos_machine_configuration_apply.controlplane["192.168.1.26"]'
$ # wait for them to all show waiting to bootstrap
$ talosctl bootstrap -e ${_node} -n ${_node}
$ terraform apply
$ export _maindir=$(pwd)
$ find . -type d -name charts | xargs rm -rf
$ cd k8s/prod/vault-secrets-operator; kustomize build --enable-helm | k apply -f -; bash setup.sh; cd ${_maindir}
$ cd k8s/argo; kustomize build --enable-helm | k apply -f -; cd ${_maindir}
$ cd k8s/prod
$ for i in $(find . -type d -maxdepth 1); do cd ${_maindir}/k8s/prod/${i}; kustomize build --enable-helm | k apply -f -; done
```

To upgrade (see AGENTS.md for the full order). Nodes first, one at a time,
on each node's schematic from locals.tf:

```sh
# Pi 4s (rpi_overlay_sha)
$ talosctl upgrade --nodes 192.168.1.19 --image factory.talos.dev/installer/8c0ab3c46bd174822da61ad52d4f014b05dc7e7d7dd8910bd2b57b0811086d1e:v1.14.2
# klipper, Pi 5 (rpi5_overlay_sha)
$ talosctl upgrade --nodes 192.168.1.69 --image factory.talos.dev/installer/0f774a083686a512e4f912ade768ab366351b3d457fdbcb188c6cf7223cc5791:v1.14.2
# cluster41, bare metal (bare_metal_sha)
$ talosctl upgrade --nodes 192.168.1.32 --image factory.talos.dev/installer/c74594ca0d5f8b6fe7e6a73c1258da7dd48cf8278684f4d40b996a248635fb95:v1.14.2

# then Kubernetes
$ talosctl upgrade-k8s --nodes 192.168.1.22 --to v1.37.2
```
