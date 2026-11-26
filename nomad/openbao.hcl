job "openbao" {
  datacenters = ["dc1"]

  group "openbao" {

    network {
      port "http" {
        static = 8200
      }
    }

    task "openbao" {
      driver = "docker"

      template {
        data = <<EOH
ui = true

api_addr     = "http://192.168.3.2:8200"
cluster_addr = "http://127.0.0.1:8201"

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = 1

  # The NAS Datadog agent's vault check scrapes /v1/sys/metrics with
  # no_token; without this it 403s.
  telemetry {
    unauthenticated_metrics_access = true
  }
}

# Required for /v1/sys/metrics?format=prometheus.
telemetry {
  prometheus_retention_time = "24h"
  disable_hostname          = true
}

storage "raft" {
  path    = "/openbao/data"
  node_id = "synology"
}

# Auto-unseal from a key file on the NAS, outside every shared folder.
# Key: 32 random bytes, owned 100:1000 (openbao), mode 0400. Losing it loses the data.
seal "static" {
  current_key_id = "20261125-1"
  current_key    = "file:///openbao/seal/unseal-20261125-1.key"
}
EOH

        destination = "local/server.hcl"
      }

      config {
        image = "quay.io/openbao/openbao:2.7.3"

        entrypoint = ["bao"]

        command = "server"

        args = [
          "-config=/openbao/config.d/server.hcl",
        ]

        ports = ["http"]

        volumes = [
          "/volume1/openbao:/openbao/data",
          "/volume1/@appdata/openbao:/openbao/seal:ro",
          "local/server.hcl:/openbao/config.d/server.hcl",
        ]
      }

      resources {
        cpu    = 1000
        memory = 512
      }
    }
  }
}
