#!/usr/bin/env bash
# Validate every node's Talos machine config exactly as this terraform root
# would build it: the same config_patches (local.controlplane_patches /
# local.worker_patches), generated for local.talos_version, then checked by
# `talosctl validate --strict` from that same Talos release.
#
# Needs no Vault and no cluster. The secrets bundle is generated fresh and
# thrown away, and Vault-backed locals are overridden with placeholders, so
# nothing real can end up in CI logs.
#
# Usage: terraform/talos/validate.sh   (terraform and curl on PATH)
set -euo pipefail

root=$(cd "$(dirname "$0")" && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

cp "$root"/*.tf "$work/"
cp -r "$root/templates" "$work/"
# Override files replace locals value-by-value, cutting the only paths from
# the patches to data.vault_generic_secret.
cat >"$work/ci_override.tf" <<'EOF'
locals {
  machine_secrets = { secrets = { machine_token = "ci-placeholder" } } # pragma: allowlist secret
  extensions      = { tailscale = { env = { TS_AUTHKEY = "ci-placeholder" } } } # pragma: allowlist secret
}
EOF

terraform -chdir="$work" init -backend=false -input=false >/dev/null
# One line (console reads stdin per line); base64 so console's HCL string
# quoting can't touch the JSON.
echo 'base64encode(jsonencode({talos_version = local.talos_version, kubernetes_version = local.kubernetes_version, controlplane = local.controlplane_patches, worker = local.worker_patches}))' |
  terraform -chdir="$work" console | tr -d '"' | base64 -d >"$work/patches.json"

read -r talos_version kubernetes_version < <(python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
print(d["talos_version"], d["kubernetes_version"])' "$work/patches.json")

talosctl=$work/talosctl
curl -fsSL -o "$talosctl" \
  "https://github.com/siderolabs/talos/releases/download/${talos_version}/talosctl-linux-amd64"
chmod +x "$talosctl"
"$talosctl" gen secrets -o "$work/secrets.yaml" >/dev/null

# One directory per node, one file per patch, in terraform's order.
python3 - "$work" <<'EOF'
import json, os, sys
work = sys.argv[1]
d = json.load(open(f"{work}/patches.json"))
for role in ("controlplane", "worker"):
    for node, patches in d[role].items():
        out = f"{work}/nodes/{role}/{node}"
        os.makedirs(out)
        for i, patch in enumerate(patches):
            with open(f"{out}/{i:02d}.yaml", "w") as f:
                f.write(patch)
EOF

failed=0
for dir in "$work"/nodes/*/*; do
  role=$(basename "$(dirname "$dir")")
  node=$(basename "$dir")
  args=()
  for patch in "$dir"/*.yaml; do args+=(--config-patch "@$patch"); done
  "$talosctl" gen config prod https://192.168.1.254:6443 \
    --with-secrets "$work/secrets.yaml" \
    --talos-version "$talos_version" \
    --kubernetes-version "$kubernetes_version" \
    --output-types "$role" "${args[@]}" \
    -o "$dir/config.yaml" >/dev/null 2>&1 ||
    { echo "FAIL $role $node: talosctl gen config rejected the patches"; failed=1; continue; }
  if out=$("$talosctl" validate --mode metal --strict -c "$dir/config.yaml" 2>&1); then
    echo "ok   $role $node"
  else
    echo "FAIL $role $node"; echo "$out" | sed 's/^/     /'; failed=1
  fi
done
echo "talos ${talos_version}, kubernetes ${kubernetes_version}"
exit "$failed"
