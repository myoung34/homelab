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
}

storage "raft" {
  path    = "/openbao/data"
  node_id = "synology"
}

# Auto-unseal from a key file on the NAS, outside every shared folder.
# See docs/superpowers/specs/2026-11-25-openbao-migration-design.md.
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
