#!/usr/bin/env bash
# SECRETS_FILE is the output of `k get secrets -A -oyaml` that you want to restore back into vault
set -euo pipefail

# Usage:
#   ./restore-eso-to-vault.sh secrets.yaml
#
# Requires:
#   jq
#   yq
#   curl
#
# Environment:
#   VAULT_ADDR
#   VAULT_TOKEN
#
# Example:
#   export VAULT_ADDR=http://192.168.3.2:8200
#   export VAULT_TOKEN=...
#   ./restore-eso-to-vault.sh ~/Downloads/k8s-secrets.yaml

SECRETS_FILE="$1"

tmpdir=$(mktemp -d)

cleanup() {
  rm -rf "$tmpdir"
}
trap cleanup EXIT

VAULT_ADDR="${VAULT_ADDR%/}"

echo "[*] Indexing Kubernetes secrets..."
yq -o=json '.items[]' "$SECRETS_FILE" > "$tmpdir/secrets.jsonl"

find . -name vault.yaml | while read -r vaultfile; do

  echo
  echo "=== Processing $vaultfile ==="

  yq -o=json '
    select(.kind == "VaultStaticSecret")
  ' "$vaultfile" | jq -c '.' | while read -r vss; do

    type=$(echo "$vss" | jq -r '.spec.type // empty')

    if [[ "$type" != "kv-v2" ]]; then
      echo "  Skipping unsupported type: $type"
      continue
    fi

    mount=$(
      echo "$vss" \
        | jq -r '.spec.mount // empty' \
        | sed 's:^/*::' \
        | sed 's:/*$::'
    )

    path=$(
      echo "$vss" \
        | jq -r '.spec.path // empty' \
        | sed 's:^/*::'
    )

    k8s_secret=$(
      echo "$vss" \
        | jq -r '.spec.destination.name // empty'
    )

    if [[ -z "$mount" || -z "$path" || -z "$k8s_secret" ]]; then
      echo "  WARNING: missing mount/path/secret name"
      continue
    fi

    vault_api_path="$mount/data/$path"
    vault_display_path="$mount/$path"

    echo "Restoring:"
    echo "  K8s Secret: $k8s_secret"
    echo "  Vault Path: $vault_display_path"
    echo "  API URL:    $VAULT_ADDR/v1/$vault_api_path"

    matches=$(
      jq -c \
        --arg name "$k8s_secret" \
        '
        select(.metadata.name == $name)
        ' "$tmpdir/secrets.jsonl"
    )

    count=$(printf "%s\n" "$matches" | grep -c '^' || true)

    if [[ "$count" -eq 0 ]]; then
      echo "  WARNING: Secret not found"
      continue
    fi

    if [[ "$count" -gt 1 ]]; then
      echo "  WARNING: Multiple matching secrets found:"
      echo "$matches" \
        | jq -r '.metadata.namespace + "/" + .metadata.name'
      continue
    fi

    secret_json="$matches"

    namespace=$(
      echo "$secret_json" \
        | jq -r '.metadata.namespace // "unknown"'
    )

    echo "  Found in namespace: $namespace"

    payload_file="$tmpdir/payload.json"

    # Decode Kubernetes secret values from base64
    if ! echo "$secret_json" | jq '
      (.data // {})
      | with_entries(
          .value |= @base64d
        )
      | del(._raw)
    ' > "$payload_file"; then
      echo "  ERROR: Failed decoding secret data"
      continue
    fi

    # Skip empty payloads
    if [[ "$(jq 'length' "$payload_file")" -eq 0 ]]; then
      echo "  WARNING: Empty secret payload"
      continue
    fi

    wrapped_payload="$tmpdir/wrapped.json"

    # Wrap for Vault KV v2 API
    jq -n \
      --slurpfile data "$payload_file" \
      '{data:$data[0]}' > "$wrapped_payload"

    echo "  Writing to Vault..."

    if ! curl -sS \
      --fail \
      --header "X-Vault-Token: $VAULT_TOKEN" \
      --header "Content-Type: application/json" \
      --request POST \
      --data @"$wrapped_payload" \
      "$VAULT_ADDR/v1/$vault_api_path" >/dev/null; then

      echo "  ERROR: Failed to write secret"
      continue
    fi

    echo "  Success."

  done

done

echo
echo "[✓] Restore complete."
