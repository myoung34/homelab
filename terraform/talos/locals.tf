locals {
  cluster_name       = "prod"
  cluster_endpoint   = "https://192.168.1.254:6443"
  talos_version      = "v1.13.7"
  kubernetes_version = "v1.36.2"

  rpi_overlay_sha   = "1ebcf8682462cead022eabbb8f4e1b4127ab53054a3fb0ed705989e5feb0af28" # pragma: allowlist secret
  rpi_overlay_image = "factory.talos.dev/installer/${local.rpi_overlay_sha}:${local.talos_version}"

  rpi5_overlay_sha   = "0f774a083686a512e4f912ade768ab366351b3d457fdbcb188c6cf7223cc5791" # pragma: allowlist secret
  rpi5_overlay_image = "factory.talos.dev/installer/${local.rpi5_overlay_sha}:${local.talos_version}"

  # Bare-metal AMD (amdgpu) node - already imaged/booted at v1.13.8, independent
  # of the shared talos_version above. Regenerate via:
  #   curl -X POST --data-binary @bare.yaml https://factory.talos.dev/schematics
  # and drop the returned "id" in below.
  bare_metal_sha   = "REPLACE_ME_WITH_FACTORY_SCHEMATIC_ID" # pragma: allowlist secret
  bare_metal_image = "factory.talos.dev/installer/${local.bare_metal_sha}:v1.13.8"

  extensions = {
    tailscale = {
      env = {
        TS_AUTHKEY = data.vault_generic_secret.talos.data["tailscale_authkey"]
      }
    }
  }

  temp_cert_sans = [] # useful when migrating controlplane nodes and having to add then remove
  cert_sans      = setunion(keys(local.node_data.controlplanes), local.temp_cert_sans)

  node_data = {
    controlplanes = {
      "192.168.1.22" = {
        hostname              = "cluster13"
        install_disk          = "/dev/sda"
        image                 = local.rpi_overlay_image
        network_hardware_addr = "dc*"
        kubernetes_version    = ""
      },
      "192.168.1.25" = {
        hostname              = "cluster22"
        install_disk          = "/dev/sda"
        image                 = local.rpi_overlay_image
        network_hardware_addr = "e4*"
        kubernetes_version    = ""
      },
      "192.168.1.26" = {
        hostname              = "cluster23"
        install_disk          = "/dev/sda"
        image                 = local.rpi_overlay_image
        network_hardware_addr = "e4*"
        kubernetes_version    = ""
      },
    }
    workers = {
      "192.168.1.19" = {
        hostname               = "cluster11"
        install_disk           = "/dev/sda"
        image                  = local.rpi_overlay_image
        kubernetes_version     = ""
        extra_device           = ""
        mount_point            = ""
        longhorn_disk_selector = ""
        ephemeral_max_size     = ""
        longhorn_min_size      = ""
        #network_hardware_addr = "00:e0*"
      },
      "192.168.1.21" = {
        hostname               = "cluster12"
        install_disk           = "/dev/sda"
        image                  = local.rpi_overlay_image
        kubernetes_version     = ""
        extra_device           = ""
        mount_point            = ""
        longhorn_disk_selector = ""
        ephemeral_max_size     = ""
        longhorn_min_size      = ""
      },
      "192.168.1.23" = {
        hostname               = "cluster14"
        install_disk           = "/dev/sda"
        image                  = local.rpi_overlay_image
        kubernetes_version     = ""
        extra_device           = ""
        mount_point            = ""
        longhorn_disk_selector = ""
        ephemeral_max_size     = ""
        longhorn_min_size      = ""

      },
      "192.168.1.24" = {
        hostname               = "cluster21"
        install_disk           = "/dev/sda"
        image                  = local.rpi_overlay_image
        kubernetes_version     = ""
        extra_device           = ""
        mount_point            = ""
        longhorn_disk_selector = ""
        ephemeral_max_size     = ""
        longhorn_min_size      = ""
      },
      "192.168.1.27" = {
        hostname               = "cluster24"
        install_disk           = "/dev/sda"
        image                  = local.rpi_overlay_image
        kubernetes_version     = ""
        extra_device           = ""
        mount_point            = ""
        longhorn_disk_selector = ""
        ephemeral_max_size     = ""
        longhorn_min_size      = ""
      },
      "192.168.1.69" = {
        hostname               = "klipper"
        install_disk           = "/dev/nvme0n1"
        image                  = local.rpi5_overlay_image
        kubernetes_version     = ""
        extra_device           = ""
        mount_point            = ""
        longhorn_disk_selector = "disk.transport == \"nvme\""
        ephemeral_max_size     = "64GB"
        longhorn_min_size      = "50GB"
      },
      "192.168.0.251" = {
        hostname           = "gpu1"
        install_disk       = "/dev/nvme0n1"
        image              = local.bare_metal_image
        kubernetes_version = ""
        extra_device       = ""
        mount_point        = ""
        # 1TB NVMe, single-disk: same disk serves EPHEMERAL (capped at 64GB)
        # and the "longhorn" UserVolumeConfig (floor of 900GB, grows to fill
        # whatever's left).
        longhorn_disk_selector = "disk.transport == \"nvme\""
        ephemeral_max_size     = "64GB"
        longhorn_min_size      = "900GB"
      },
    }
  }

  machine_secrets = {
    certs = {
      etcd = {
        cert = data.vault_generic_secret.talos.data["etcd.cert"]
        key  = data.vault_generic_secret.talos.data["etcd.key"]
      }
      k8s = {
        cert = data.vault_generic_secret.talos.data["k8s.cert"]
        key  = data.vault_generic_secret.talos.data["k8s.key"]
      }
      k8s_aggregator = {
        cert = data.vault_generic_secret.talos.data["k8s_aggregator.cert"]
        key  = data.vault_generic_secret.talos.data["k8s_aggregator.key"]
      }
      k8s_serviceaccount = {
        key = data.vault_generic_secret.talos.data["k8s_serviceaccount.key"]
      }
      os = {
        cert = data.vault_generic_secret.talos.data["os.cert"]
        key  = data.vault_generic_secret.talos.data["os.key"]
      }
    }
    cluster = {
      id     = data.vault_generic_secret.talos.data["cluster.id"]
      secret = data.vault_generic_secret.talos.data["cluster.secret"]
    }
    secrets = {
      machine_token               = data.vault_generic_secret.talos.data["machine.token"]
      bootstrap_token             = data.vault_generic_secret.talos.data["secrets.bootstrap_token"]
      secretbox_encryption_secret = data.vault_generic_secret.talos.data["secrets.secretbox_encryption_secret"]
    }
    trustdinfo = {
      token = ""
    }
  }
  client_configuration = {
    ca_certificate     = data.vault_generic_secret.talos.data["client_configuration.ca_certificate"]
    client_certificate = data.vault_generic_secret.talos.data["client_configuration.client_certificate"]
    client_key         = data.vault_generic_secret.talos.data["client_configuration.client_key"]
  }
}
