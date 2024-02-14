To get the argo workflow token:

```
kubectl -n argocd exec $(kubectl get pod -n argocd -l 'app.kubernetes.io/name=argo-workflows-server' -o jsonpath='{.items[0].metadata.name}') -- argo auth token
```
