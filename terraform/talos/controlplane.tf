locals {
  controlplane_patches = {
    "192.168.1.22" = templatefile("templates/controlplane.yaml.tmpl", {
      hostname      = "cluster13"
      machine_token = data.talos_client_configuration.cluster13.machine_token
      image         = "factory.talos.dev/installer/${local.bare_metal_sha}:v1.14.2"
      install_disk  = "${install_disk}"
    })
    "192.168.1.25" = templatefile("templates/controlplane.yaml.tmpl", {
      hostname      = "cluster22"
      machine_token = data.talos_client_configuration.cluster22.machine_token
      image         = "factory.talos.dev/installer/${local.rpi_overlay_sha}:v1.14.2"
      install_disk  = "${install_disk}"
    })
    "192.168.1.24" = templatefile("templates/controlplane.yaml.tmpl", {
      hostname      = "cluster21"
      machine_token = data.talos_client_configuration.cluster21.machine_token
      image         = "factory.talos.dev/installer/${local.rpi_overlay_sha}:v1.14.2"
      install_disk  = "${install_disk}"
    })
  }
}
