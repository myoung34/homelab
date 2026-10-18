# terraform/talos

Talos node config for the cluster. Read this before any change here: a Talos
or Kubernetes upgrade, a template edit, or adding or removing a node.

## How config is built

`data "talos_machine_configuration"` generates each node's base config for
`local.talos_version`. Terraform then patches it with
`local.controlplane_patches` or `local.worker_patches`, which render the files
in `templates/`.

`talos_version` is the config *contract*, not only the installer tag. It picks
the generator's defaults and its document format, so bumping it changes the
base config every node gets, even with no template edits.

## Validate every change

Run `terraform/talos/validate.sh` before opening a PR. It renders every
node's config exactly as terraform builds it and runs
`talosctl validate --strict` from the matching Talos release. It needs
terraform, curl and python3, and no Vault or cluster access.

CI runs the same script on every push that touches this directory
(`.github/workflows/talos.yaml`, check name "Validate Talos config"). A red
check means Talos would reject the config at `terraform apply`. If you can't
run the script yourself, read the PR's check result before calling it ready.

A green check proves the config is valid, not that it still does what it did.
See "Keep every behaviour".

## Upgrade Talos and Kubernetes

1. Upgrade the nodes first, still on the old config:
   `talosctl upgrade --image <schematic>:<version>` on every node. An older
   node rejects config documents it doesn't know (see the comment in
   `worker.tf`), so `terraform apply` has to wait.
1. Upgrade Kubernetes with `talosctl upgrade-k8s --to <version>`. Take the
   version from the "Component Updates" section of that Talos release's notes
   and state the mapping in the PR.
1. In one PR, bump `talos_version` and `kubernetes_version` in `locals.tf`,
   migrate the templates, and update the pins listed below. Apply it after
   merge.

Every apply regenerates the whole config from the new contract, so the
target is what the new version generates, not what a node runs today:

- Release-note lines like "upgraded clusters keep the old behaviour" describe
  an in-place upgrade and don't apply here.
- An upgrade never rewrites a node's config. Talos changes it only through
  `apply-config`, `patch` or `edit`, so an upgraded node keeps its old shape,
  and `talosctl get mc` returns what you already have.

Take the target shape from a freshly generated config, and diff each rendered
template against it:

```sh
talosctl gen config ref https://x:6443 --talos-version <version> \
  -o "$TMPDIR/ref"
```

### Migrating templates to a new version

- Each release moves more v1alpha1 fields into typed documents. A deprecated
  field and its replacement document can't both be set, so rewrite every
  moved field in `templates/` as its document. Look up each field in the
  target version's document map:
  `https://docs.siderolabs.com/talos/<version>/reference/configuration/document-map`.
- When a field has no replacement document, stop and ask Mark before
  migrating that template. Example: in 1.14, `.machine.kubelet.extraMounts`
  can't be combined with `KubeletConfig`, and both Longhorn templates use it.
- Read the release's "What's New" for documents the generator now emits by
  default, and name each one in the PR body with whether you pin it. Example:
  1.14 adds `SecurityProfileConfig` with `workloadIsolation: true`, which
  blocks pods from the host iscsid that Longhorn's v1 engine uses.

## Keep every behaviour

Each block in `templates/` exists for a reason, usually written in the
comment above it. For example, the cluster41 watchdog in
`bare-metal.yaml.tmpl` came out of a real hard lock. Carry every block across
a change, migrating its format where needed. When a block is removed or
renamed, name it and its replacement in the PR body. A block that disappears
without a named replacement is a regression, even when validation passes.

## Pins that follow `talos_version`

Grep the repo for the old version string, then update or justify every hit.
Known pins:

- `k8s/prod/kagent/homelab-agent.yaml`: the `ghcr.io/siderolabs/talosctl`
  image volume
- `k8s/prod/workflows/etcdsnapshot.yaml`: the talosctl download URL
- `README.md` in this directory: the upgrade example
