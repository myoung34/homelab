#!/bin/bash

# Backup Vault data
echo "Starting Vault backup..."
vault operator raft snapshot save /backup/vault_snapshot.snap
echo "Vault backup completed."

# Print GitHub token
echo ${GITHUB_TOKEN}

# Notify completion
echo "Backup process finished."
