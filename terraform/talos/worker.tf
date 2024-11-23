data "talos_machine_configuration" "worker" {
  cluster_name     = local.cluster_name
  cluster_endpoint = local.cluster_endpoint
  machine_type     = "worker"
  machine_secrets  = local.machine_secrets
}

resource "talos_machine_configuration_apply" "worker" {
  client_configuration        = local.client_configuration
  machine_configuration_input = data.talos_machine_configuration.worker.machine_configuration
  for_each                    = local.node_data.workers
  node                        = each.key
  config_patches = flatten([
    templatefile("${path.module}/templates/install-disk-and-hostname.yaml.tmpl", {
      hostname           = each.value.hostname
      install_disk       = each.value.install_disk
      image              = each.value.image
      machine_token      = local.machine_secrets.secrets.machine_token
      talos_version      = length(each.value.talos_version) == 0 ? local.talos_version : each.value.talos_version
      kubernetes_version = length(each.value.kubernetes_version) == 0 ? local.kubernetes_version : each.value.kubernetes_version
      tailscale_version  = local.extensions.tailscale.version
    }),
    templatefile("${path.module}/templates/extensionserviceconfig.yaml.tmpl", {
      name = "tailscale"
      env  = local.extensions.tailscale.env
    }),
    length(each.value.mount_point) == 0 ? [] : [templatefile("${path.module}/templates/worker-with-extra-disk.yaml.tmpl", {
      mount_point  = each.value.mount_point
      extra_device = each.value.extra_device
    })]
  ])
}
