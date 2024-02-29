#!/bin/bash
echo "Bearer $(kubectl -n argocd get secret admin-user -oyaml | yq .data.token | base64 -d)" | pbcopy
