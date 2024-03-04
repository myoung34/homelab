locals {
  cluster_name       = "prod"
  cluster_endpoint   = "https://192.168.1.254:6443"
  talos_version      = "v1.6.5"
  kubernetes_version = "v1.29.0"

  node_data = {
    controlplanes = {
      "192.168.1.22" = {
        hostname              = "cluster13"
        install_disk          = "/dev/sda"
        network_hardware_addr = "d*"
        talos_version         = ""
        kubernetes_version    = ""
      },
      "192.168.1.25" = {
        hostname              = "cluster22"
        install_disk          = "/dev/sda"
        network_hardware_addr = "e4*"
        talos_version         = ""
        kubernetes_version    = ""
      },
      "192.168.1.26" = {
        hostname              = "cluster23"
        install_disk          = "/dev/sda"
        network_hardware_addr = "e4*"
        talos_version         = ""
        kubernetes_version    = ""
      },
    }
    workers = {
      "192.168.1.19" = {
        hostname           = "cluster11"
        install_disk       = "/dev/sda"
        talos_version      = ""
        kubernetes_version = ""
        extra_device       = ""
        mount_point        = ""
      },
      "192.168.1.21" = {
        hostname           = "cluster12"
        install_disk       = "/dev/sda"
        talos_version      = ""
        kubernetes_version = ""
        extra_device       = ""
        mount_point        = ""
      },
      "192.168.1.23" = {
        hostname           = "cluster14"
        install_disk       = "/dev/sda"
        talos_version      = ""
        kubernetes_version = ""
        extra_device       = "/dev/disk/by-id/usb-SSK_SSK_Storage_012345678923-0:0"
        mount_point        = "/var/mnt/storage"

      },
      "192.168.1.24" = {
        hostname           = "cluster21"
        install_disk       = "/dev/sda"
        talos_version      = ""
        kubernetes_version = ""
        extra_device       = ""
        mount_point        = ""
      },
      "192.168.1.27" = {
        hostname           = "cluster24"
        install_disk       = "/dev/sda"
        talos_version      = ""
        kubernetes_version = ""
        extra_device       = ""
        mount_point        = ""
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
