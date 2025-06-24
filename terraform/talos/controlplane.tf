data "talos_machine_configuration" "controlplane" {
  cluster_name     = local.cluster_name
  cluster_endpoint = local.cluster_endpoint
  machine_type     = "controlplane"
  machine_secrets  = local.machine_secrets
}

resource "talos_machine_configuration_apply" "controlplane" {
  client_configuration        = local.client_configuration
  machine_configuration_input = data.talos_machine_configuration.controlplane.machine_configuration
  for_each                    = local.node_data.controlplanes
  node                        = each.key
  config_patches = [
    templatefile("${path.module}/templates/install-disk-and-hostname.yaml.tmpl", {
      hostname           = each.value.hostname
      install_disk       = each.value.install_disk
      image              = each.value.image
      machine_token      = local.machine_secrets.secrets.machine_token
      talos_version      = length(each.value.talos_version) == 0 ? local.talos_version : each.value.talos_version
      kubernetes_version = length(each.value.kubernetes_version) == 0 ? local.kubernetes_version : each.value.kubernetes_version
      extensions         = local.extensions
    }),
    templatefile("${path.module}/templates/controlplane.yaml.tmpl", {
      talos_version         = length(each.value.talos_version) == 0 ? local.talos_version : each.value.talos_version
      kubernetes_version    = length(each.value.kubernetes_version) == 0 ? local.kubernetes_version : each.value.kubernetes_version
      network_hardware_addr = each.value.network_hardware_addr
      cert_sans             = local.cert_sans
    }),
    templatefile("${path.module}/templates/extensionserviceconfig.yaml.tmpl", {
      name = "tailscale"
      env  = local.extensions.tailscale.env
    }),
  ]
}
