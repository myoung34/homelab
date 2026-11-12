Unpackerr
=========

Extracts RAR'd downloads so Radarr can import them. It polls Radarr's queue,
extracts each completed archive next to itself (keeping the `.rar` files so
the torrent keeps seeding), and deletes the extracted copy a few minutes
after Radarr imports it. The library keeps the file as a hardlink.

## Setup

```bash
vault kv put secret/unpackerr \
  UN_RADARR_0_API_KEY="$(kubectl -n radarr exec deploy/radarr -- \
    sed -n 's:.*<ApiKey>\(.*\)</ApiKey>.*:\1:p' /config/config.xml)"
vault policy write unpackerr - <<'HCL'
path "secret/data/unpackerr" { capabilities = ["read"] }
path "secret/metadata/unpackerr" { capabilities = ["read", "list"] }
HCL
vault write auth/kubernetes/role/unpackerr \
  bound_service_account_names=default \
  bound_service_account_namespaces=unpackerr \
  policies=unpackerr token_policies=unpackerr ttl=24h
```
