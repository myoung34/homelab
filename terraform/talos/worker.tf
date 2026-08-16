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
      kubernetes_version = length(each.value.kubernetes_version) == 0 ? local.kubernetes_version : each.value.kubernetes_version
    }),
    templatefile("${path.module}/templates/extensionserviceconfig.yaml.tmpl", {
      name = "tailscale"
      env  = local.extensions.tailscale.env
    }),
    length(each.value.longhorn_disk_selector) == 0 ? [templatefile("${path.module}/templates/longhorn.yaml.tmpl", {})] : [templatefile("${path.module}/templates/longhorn-dedicated-volume.yaml.tmpl", {
      disk_selector      = each.value.longhorn_disk_selector
      ephemeral_max_size = each.value.ephemeral_max_size
      longhorn_min_size  = each.value.longhorn_min_size
    })],
    length(each.value.mount_point) == 0 ? [] : [templatefile("${path.module}/templates/worker-with-extra-disk.yaml.tmpl", {
      mount_point  = each.value.mount_point
      extra_device = each.value.extra_device
    })]
  ])
}
