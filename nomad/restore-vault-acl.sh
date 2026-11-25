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

  # One policy per auth ref, covering every VaultStaticSecret that uses it
  # (writing one per secret let the last one overwrite the rest).
  for auth_ref in $(jq -r '[.[] | select(.kind=="VaultStaticSecret") | .spec.vaultAuthRef] | unique | .[]' /tmp/vault_objects.json); do

    echo
    echo "Creating policy: $auth_ref"

    jq -r --arg ref "$auth_ref" '
      .[] | select(.kind=="VaultStaticSecret" and .spec.vaultAuthRef==$ref)
      | (.spec.mount | sub("/+$"; "")) as $m
      | "path \"\($m)/data/\(.spec.path)\" {\n  capabilities = [\"read\"]\n}\n\npath \"\($m)/metadata/\(.spec.path)\" {\n  capabilities = [\"read\", \"list\"]\n}\n"
    ' /tmp/vault_objects.json >/tmp/policy.hcl

    vault policy write "$auth_ref" /tmp/policy.hcl

  done

  # Process VaultAuth objects
  jq -c '.[] | select(.kind=="VaultAuth")' /tmp/vault_objects.json | while read -r vauth; do

    role=$(echo "$vauth" | jq -r '.spec.kubernetes.role')
    sa=$(echo "$vauth" | jq -r '.spec.kubernetes.serviceAccount')
    namespace=$(echo "$vauth" | jq -r '.metadata.namespace // empty')

    # Missing namespace: kustomization's namespace, then the directory name
    if [[ -z "$namespace" || "$namespace" == "null" ]]; then
      namespace=$(yq -r '.namespace // ""' "$(dirname "$vaultfile")/kustomization.yaml" 2>/dev/null || true)
    fi
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
