# Notes

export K8S_VAULT_SA_SECRET="vault-auth-token"
kubectl -n vault-secrets-operator get secret/${K8S_VAULT_SA_SECRET} -o json | jq -r '.data["ca.crt"]' | base64 -d > ca.crt
kubectl -n vault-secrets-operator get secret/${K8S_VAULT_SA_SECRET} -o json | jq -r '.data["token"]' | base64 -d > sa.token
vault write auth/kubernetes/config  kubernetes_host=https://192.168.1.254:6443 kubernetes_ca_cert=@ca.crt token_reviewer_jwt=@sa.token disable_iss_validation=true

# example
#vault write auth/kubernetes/role/actions-runner \
#  bound_service_account_names=actions-runner \
#  bound_service_account_namespaces=actions-runner \
#  policies=actions-runner \
#  token_policies=actions-runner
