#!/usr/bin/env bash
# Copy Vault (or OpenBao) state into a fresh OpenBao.
#
# Usage (VAULT_ADDR/VAULT_TOKEN point at the server being read or written):
#   ./openbao-bootstrap.sh export DIR   # old Vault -> DIR (holds plaintext secrets; created 0700)
#   ./openbao-bootstrap.sh import DIR   # DIR -> new OpenBao (root token from `bao operator init`)
#   ./openbao-bootstrap.sh verify DIR   # every KV path in DIR matches the server
#
# Copies: KV v2 at secret/, policies, jwt-nomad/ auth (config + roles),
# kubernetes/ auth (roles; CA and reviewer JWT are re-read from the cluster),
# token roles. Tokens and identity entities are not copied; clients re-auth.
#
# Requires: vault (or bao) CLI, jq, kubectl (import only, read-only).
set -euo pipefail

cmd="${1:?usage: $0 export|import|verify DIR}"
dir="${2:?usage: $0 export|import|verify DIR}"
VAULT="${VAULT_CLI:-vault}"

# Legacy aliases returned by reads; writing them next to token_* fails or is ambiguous.
strip='with_entries(select(.value != null and .value != "" and .value != [] and .value != {}))
  | del(.name, .policies, .ttl, .max_ttl, .explicit_max_ttl, .period, .bound_cidrs, .num_uses)'

kv_paths() {
  local p="$1"
  "$VAULT" kv list -format=json "secret/$p" 2>/dev/null | jq -r '.[]' | while read -r child; do
    if [[ "$child" == */ ]]; then kv_paths "$p$child"; else echo "$p$child"; fi
  done
}

do_export() {
  umask 077
  mkdir "$dir" # fails if it exists, so an old export is never mixed in
  mkdir -p "$dir"/{kv,policies,jwt-nomad,kubernetes,token}

  kv_paths "" | while read -r p; do
    mkdir -p "$dir/kv/$(dirname "$p")"
    "$VAULT" kv get -format=json "secret/$p" | jq '.data.data' >"$dir/kv/$p.json"
  done

  "$VAULT" policy list | grep -vx root | while read -r p; do
    "$VAULT" policy read "$p" >"$dir/policies/$p.hcl"
  done

  "$VAULT" read -format=json auth/jwt-nomad/config | jq '.data' >"$dir/jwt-nomad/config.json"
  for r in $("$VAULT" list -format=json auth/jwt-nomad/role | jq -r '.[]'); do
    "$VAULT" read -format=json "auth/jwt-nomad/role/$r" | jq '.data' >"$dir/jwt-nomad/$r.json"
  done

  "$VAULT" read -format=json auth/kubernetes/config |
    jq '.data | {kubernetes_host, disable_iss_validation}' >"$dir/kubernetes/config.json"
  for r in $("$VAULT" list -format=json auth/kubernetes/role | jq -r '.[]'); do
    "$VAULT" read -format=json "auth/kubernetes/role/$r" | jq '.data' >"$dir/kubernetes/$r.json"
  done

  for r in $("$VAULT" list -format=json auth/token/roles | jq -r '.[]'); do
    "$VAULT" read -format=json "auth/token/roles/$r" | jq '.data' >"$dir/token/$r.json"
  done

  echo "exported $(find "$dir/kv" -name '*.json' | wc -l) KV paths, $(find "$dir/policies" -name '*.hcl' | wc -l) policies to $dir"
}

do_import() {
  [[ -d "$dir/kv" ]] || { echo "$dir is not an export" >&2; exit 1; }
  # Guard: old Vault is file-backed, OpenBao is raft. Never import into the source.
  local storage
  storage="$("$VAULT" status -format=json | jq -r '.storage_type')"
  [[ "$storage" == raft ]] || { echo "refusing import: $VAULT_ADDR storage is '$storage', want raft" >&2; exit 1; }

  "$VAULT" secrets enable -path=secret -version=2 kv
  "$VAULT" auth enable -path=jwt-nomad jwt
  "$VAULT" auth enable kubernetes

  for f in "$dir"/policies/*.hcl; do
    "$VAULT" policy write "$(basename "$f" .hcl)" "$f"
  done

  jq "$strip" "$dir/jwt-nomad/config.json" | "$VAULT" write auth/jwt-nomad/config -
  for f in "$dir"/jwt-nomad/*.json; do
    [[ "$(basename "$f")" == config.json ]] && continue
    jq "$strip" "$f" | "$VAULT" write "auth/jwt-nomad/role/$(basename "$f" .json)" -
  done

  local sa=vault-secrets-operator/vault-auth-token tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  kubectl -n "${sa%/*}" get secret "${sa#*/}" -o jsonpath='{.data.ca\.crt}' | base64 -d >"$tmp/ca.crt"
  kubectl -n "${sa%/*}" get secret "${sa#*/}" -o jsonpath='{.data.token}' | base64 -d >"$tmp/sa.token"
  jq --rawfile ca "$tmp/ca.crt" --rawfile jwt "$tmp/sa.token" \
    '. + {kubernetes_ca_cert: $ca, token_reviewer_jwt: $jwt}' "$dir/kubernetes/config.json" |
    "$VAULT" write auth/kubernetes/config -
  for f in "$dir"/kubernetes/*.json; do
    [[ "$(basename "$f")" == config.json ]] && continue
    jq "$strip" "$f" | "$VAULT" write "auth/kubernetes/role/$(basename "$f" .json)" -
  done

  for f in "$dir"/token/*.json; do
    jq "$strip" "$f" | "$VAULT" write "auth/token/roles/$(basename "$f" .json)" -
  done

  (cd "$dir/kv" && find . -name '*.json') | sed 's#^\./##; s#\.json$##' | while read -r p; do
    "$VAULT" kv put -mount=secret "$p" @"$dir/kv/$p.json" >/dev/null
  done

  do_verify
}

do_verify() {
  local bad=0 p
  while read -r p; do
    if ! diff -q <(jq -S . "$dir/kv/$p.json") \
      <("$VAULT" kv get -format=json -mount=secret "$p" | jq -S '.data.data') >/dev/null; then
      echo "MISMATCH secret/$p" >&2
      bad=1
    fi
  done < <(cd "$dir/kv" && find . -name '*.json' | sed 's#^\./##; s#\.json$##')
  [[ "$bad" -eq 0 ]] && echo "all KV paths in $dir match $VAULT_ADDR"
  return "$bad"
}

case "$cmd" in
  export) do_export ;;
  import) do_import ;;
  verify) do_verify ;;
  *) echo "unknown command: $cmd" >&2; exit 1 ;;
esac
