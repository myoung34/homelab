Prowlarr
========

Indexer manager for the -arr stack. Setup, tunnel rationale, and the Vault /
NFS prerequisites are documented in one place: `k8s/prod/radarr/README.md`.

The short version: the `seedbox-tunnel` sidecar runs `autossh -D 127.0.0.1:1080`
to the seedbox, and Prowlarr's global proxy (Settings → General → Proxy) points
at it, so indexer searches leave from the seedbox IP rather than from home.
