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

To upgrade:

```
$ curl -X POST --data-binary @bare-metal.yaml https://factory.talos.dev/schematics
{"id":"b8e8fbbe1b520989e6c52c8dc8303070cb42095997e76e812fa8892393e1d176"}

$ talosctl upgrade --nodes 192.168.1.19,192.168.1.24 --image factory.talos.dev/metal-installer/b8e8fbbe1b520989e6c52c8dc8303070cb42095997e76e812fa8892393e1d176:v1.10.6

$ curl -X POST --data-binary @pi.yaml https://factory.talos.dev/schematics
{"id":"9992b4ade979cf2fc812e6f07e264d1f240d11b0d1eb795ce78771f8647a316"}

$ talosctl upgrade --nodes 192.168.1.21,192.168.1.22,192.168.1.23,192.168.1.25,192.168.1.26 --image factory.talos.dev/metal-installer/9992b4ade979cf2fc812e6f07e264d1f240d11b0d1eb795ce78771f8647a316:v1.10.6
```
