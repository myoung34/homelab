#!/usr/bin/env bash
set -euo pipefail

#
# Generates Vault policies + Kubernetes auth roles from VaultStaticSecret CRDs
#
# Requires:
#   jq
#   yq
#   vault
#
# Usage:
#   ./setup-vso-acls.sh
#

find . -name vault.yaml | while read -r vaultfile; do

  echo
  echo "=== Processing $vaultfile ==="

  yq -o=json '
    select(.kind == "VaultStaticSecret" or .kind == "VaultAuth")
  ' "$vaultfile" | jq -s '.' > /tmp/vault_objects.json

  vss_count=$(jq '[.[] | select(.kind=="VaultStaticSecret")] | length' /tmp/vault_objects.json)

  if [[ "$vss_count" -eq 0 ]]; then
    echo "  No VaultStaticSecret objects"
    continue
  fi

  # Process each VaultStaticSecret
  jq -c '.[] | select(.kind=="VaultStaticSecret")' /tmp/vault_objects.json | while read -r vss; do

    auth_ref=$(echo "$vss" | jq -r '.spec.vaultAuthRef')
    mount=$(echo "$vss" | jq -r '.spec.mount' | sed 's:/*$::')
    path=$(echo "$vss" | jq -r '.spec.path')

    echo
    echo "Creating policy for:"
    echo "  Auth Ref: $auth_ref"
    echo "  Secret:   $mount/$path"

    cat >/tmp/policy.hcl <<EOF
path "$mount/data/$path" {
  capabilities = ["read"]
}

path "$mount/metadata/$path" {
  capabilities = ["read", "list"]
}
EOF

    vault policy write "$auth_ref" /tmp/policy.hcl

    echo "  Policy created: $auth_ref"

  done

  # Process VaultAuth objects
  jq -c '.[] | select(.kind=="VaultAuth")' /tmp/vault_objects.json | while read -r vauth; do

    role=$(echo "$vauth" | jq -r '.spec.kubernetes.role')
    sa=$(echo "$vauth" | jq -r '.spec.kubernetes.serviceAccount')
    namespace=$(echo "$vauth" | jq -r '.metadata.namespace // empty')

    # Infer namespace from directory if missing
    if [[ -z "$namespace" || "$namespace" == "null" ]]; then
      namespace=$(basename "$(dirname "$vaultfile")")
    fi

    echo
    echo "Creating Kubernetes auth role:"
    echo "  Role:       $role"
    echo "  Namespace:  $namespace"
    echo "  SA:         $sa"

    vault write "auth/kubernetes/role/$role" \
      bound_service_account_names="$sa" \
      bound_service_account_namespaces="$namespace" \
      policies="$role" \
      token_policies="$role" \
      ttl=24h

    echo "  Role created: $role"

  done

done

echo
echo "[✓] Vault policies and roles created."
