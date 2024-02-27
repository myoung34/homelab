data "vault_generic_secret" "talos" {
  path = "secret/terraform/talos"
}

data "talos_client_configuration" "this" {
  cluster_name         = local.cluster_name
  client_configuration = local.client_configuration
  endpoints            = [for k, v in local.node_data.controlplanes : k]
}
