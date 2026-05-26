#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./vault-backup.sh > vault-backup.json

MOUNT="${MOUNT:-secret}"

tmp="$(mktemp)"
echo "{}" > "$tmp"

echo "[*] Enumerating Vault secrets from ${MOUNT}/ ..." >&2

walk() {
  local path="$1"

  vault kv list -format=json "${MOUNT}/${path}" 2>/dev/null \
    | jq -r '.[]' \
    | while read -r child; do

        if [[ "${child}" == */ ]]; then
          walk "${path}${child}"
          continue
        fi

        local fullpath="${path}${child}"

        echo "[*] Backing up ${MOUNT}/${fullpath}" >&2

        vault kv get -format=json "${MOUNT}/${fullpath}" \
          | jq '
              .data.data
              | with_entries(
                  .value |= (
                    tostring
                    | @base64
                  )
                )
            ' > /tmp/vault-secret.json

        jq \
          --arg path "${MOUNT}/${fullpath}" \
          --slurpfile data /tmp/vault-secret.json \
          '. + {($path): $data[0]}' \
          "$tmp" > "${tmp}.new"

        mv "${tmp}.new" "$tmp"
      done
}

walk ""

cat "$tmp"

rm -f "$tmp" /tmp/vault-secret.json
