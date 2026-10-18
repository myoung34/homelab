locals {
  cluster_name       = "prod"
  cluster_endpoint   = "https://192.168.1.254:6443"
  talos_version      = "v1.14.2"
  kubernetes_version = "v1.37.2"

  rpi_overlay_sha   = "8c0ab3c46bd174822da61ad52d4f014b05dc7e7d7dd8910bd2b57b0811086d1e" # pragma: allowlist secret
  rpi_overlay_image = "factory.talos.dev/installer/${local.rpi_overlay_sha}:${local.talos_version}"

  rpi5_overlay_sha   = "0f774a083686a512e4f912ade768ab366351b3d457fdbcb188c6cf7223cc5791" # pragma: allowlist secret
  rpi5_overlay_image = "factory.talos.dev/installer/${local.rpi5_overlay_sha}:${local.talos_version}"

  # Bare-metal amd64 + Radeon (amdgpu) schematic from bare.yaml. No overlay on
  # amd64; siderolabs/amdgpu ships both the firmware and kernel modules the
  # Radeon AI PRO R9700 / gfx1201 needs; siderolabs/amd-ucode is CPU microcode
  # and the generic initrd includes all required firmware.
  bare_metal_sha   = "d20658781038119eab2f828a96a00e1856624195c2589444368650d7f89122a9" # pragma: allowlist secret
  bare_metal_image = "factory.talos.dev/installer/${local.bare_metal_sha}:${local.talos_version}"

  # Map node positions to IPs and node-specific data. The `image` field is
  # the schematic ID. The `kubernetes_version` field is optional; it allows
  # a node-by-node upgrade if that becomes necessary.
  node_data = {
    cluster11 = {
      hostname           = "cluster11"
      install_disk       = "/dev/disk/by-id/usb-Sabrent_Unique-NT-35C4F0000927-0:0"
      image              = local.rpi_overlay_image
      ip                 = "192.168.1.11"
    }
    cluster12 = {
      hostname           = "cluster12"
      install_disk       = "/dev/disk/by-id/usb-Sabrent_Unique-NT-35C4F0000927-0:0"
      image              = local.rpi5_overlay_image
      ip                 = "192.168.1.12"
    }
    cluster13 = {
      hostname           = "cluster13"
      install_disk       = "/dev/disk/by-id/usb-Sabrent_Unique-NT-35C4F0000927-0:0"
      image              = local.rpi5_overlay_image
      ip                 = "192.168.1.13"
    }
    cluster21 = {
      hostname           = "cluster21"
      install_disk       = "/dev/disk/by-id/usb-Sabrent_Unique-NT-35C4F0000927-0:0"
      image              = local.rpi_overlay_image
      ip                 = "192.168.1.21"
    }
    cluster22 = {
      hostname           = "cluster22"
      install_disk       = "/dev/disk/by-id/usb-Sabrent_Unique-NT-35C4F0000927-0:0"
      image              = local.rpi5_overlay_image
      ip                 = "192.168.1.22"
    }
    cluster23 = {
      hostname           = "cluster23"
      install_disk       = "/dev/disk/by-id/usb-Sabrent_Unique-NT-35C4F0000927-0:0"
      image              = local.bare_metal_image
      ip                 = "192.168.1.23"
    }
  }

  # Extensions that are installed on every node: tailscale, docker, nvidia.
  # The nvidia container runtime is on by default in Talos 1.14; this does not
  # need the extension anymore.
  extensions = {
    tailscale = {
      env = {
        TS_AUTH_KEY = ""
      }
    }
    docker = {
      env = {}
    }
    nvidia = {
      env = {
        NVIDIA_RUNTIME = "nvidia"
      }
    }
  }

  # Map of extensions to include by name. Each is rendered by a template in
  # templates/.
  extensions_to_include = {
    "tailscale" = local.extensions.tailscale
    "docker"    = local.extensions.docker
    "nvidia"    = local.extensions.nvidia
  }
}
