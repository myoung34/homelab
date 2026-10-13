data "talos_machine_configuration" "controlplane" {
  cluster_name     = local.cluster_name
  cluster_endpoint = local.cluster_endpoint
  machine_type     = "controlplane"
  machine_secrets  = local.machine_secrets
  # See the note in worker.tf - this must track the nodes' Talos version, not
  # whatever pkg/machinery the provider happens to bundle.
  talos_version = local.talos_version
}

# Per-node patches, keyed by node IP. A local rather than inline in the
# resource so validate.sh can render exactly what terraform applies.
locals {
  controlplane_patches = { for ip, node in local.node_data.controlplanes : ip => [
    templatefile("${path.module}/templates/install-disk-and-hostname.yaml.tmpl", {
      hostname           = node.hostname
      install_disk       = node.install_disk
      image              = node.image
      machine_token      = local.machine_secrets.secrets.machine_token
      kubernetes_version = try(node.kubernetes_version, "") == "" ? local.kubernetes_version : node.kubernetes_version
    }),

    templatefile("${path.module}/templates/controlplane.yaml.tmpl", {
      talos_version         = try(node.talos_version, "") == "" ? local.talos_version : node.talos_version
      kubernetes_version    = try(node.kubernetes_version, "") == "" ? local.kubernetes_version : node.kubernetes_version
      network_hardware_addr = node.network_hardware_addr
      cert_sans             = local.cert_sans
    }),

    templatefile("${path.module}/templates/extensionserviceconfig.yaml.tmpl", {
      name = "tailscale"
      env  = local.extensions.tailscale.env
    }),
  ] }
}

resource "talos_machine_configuration_apply" "controlplane" {
  client_configuration        = local.client_configuration
  machine_configuration_input = data.talos_machine_configuration.controlplane.machine_configuration

  for_each = local.node_data.controlplanes

  node = each.key

  config_patches = local.controlplane_patches[each.key]
}
