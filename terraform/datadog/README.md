Datadog
=====

Monitors and log pipelines. Synthetics tests (and the monitors they own)
aren't managed here.

State lives in the shared `terraform` bucket on Fastly object storage, same as
the other stacks. The provider reads `DD_API_KEY` / `DD_APP_KEY`; the cluster's
`datadog` secret holds both:

```sh
cd terraform/datadog
S=$(kubectl -n datadog get secret datadog -o json)
export DD_API_KEY=$(echo "$S" | jq -r '.data["api-key"]' | base64 -d)
export DD_APP_KEY=$(echo "$S" | jq -r '.data["app-key-secret"]' | base64 -d)
aws-vault exec -n fastly -- terraform plan
```

`datadog_monitor.agent_not_reporting` always shows `+ new_host_delay = 300`:
the field is deprecated and the API no longer returns it. Harmless.

Change monitors here, not in the Datadog UI; UI edits show up as drift on the
next plan.
