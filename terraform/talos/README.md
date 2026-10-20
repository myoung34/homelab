# Talos Kubernetes Cluster

This Terraform root provisions the Talos Kubernetes cluster that runs most of
the estate. The cluster is built on Raspberry Pi 4s and Pi 5s on PoE racks, plus
a Rock Pi X (amd64) and a bare-metal node with a Radeon AI PRO R9700 and an RTX
2070 SUPER.

## Upgrades

Per `terraform/talos/AGENTS.md`:

- A schematic ID covers only the extensions and overlay, not the Talos version;
  `locals.tf` adds the version as the image tag.

- The typed document migration window in Talos v1.14.2 means v1alpha1 formats
  continue to work.

### Control-plane (cluster{13,21,22})

```bash
$ curl -X POST --data-binary @bare-metal.yaml https://factory.talos.dev/schematics
{"id":"b8e8fbbe1b520989e6c52c8dc8303070cb42095997e76e812fa8892393e1d176"}

$ talosctl upgrade --nodes 192.168.1.19,192.168.1.24 --image factory.talos.dev/metal-installer/b8e8fbbe1b520989e6c52c8dc8303070cb42095997e76e812fa8892393e1d176:v1.14.2
```

### Workers

```bash
$ curl -X POST --data-binary @pi.yaml https://factory.talos.dev/schematics
{"id":"9992b4ade979cf2fc812e6f07e264d1f240d11b0d1eb795ce78771f8647a316"}

$ talosctl upgrade --nodes 192.168.1.21,192.168.1.22,192.168.1.23,192.168.1.25,192.168.1.26 --image factory.talos.dev/metal-installer/9992b4ade979cf2fc812e6f07e264d1f240d11b0d1eb795ce78771f8647a316:v1.14.2
```
