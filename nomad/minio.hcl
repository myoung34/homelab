job "minio" {
  datacenters = ["dc1"]

  group "minio" {

    network {
      port "api" {
        static = 9000
      }

      port "http" {
        static = 9001
      }
    }

    task "minio" {
      driver = "docker"

      identity {
        name = "vault_default"
        aud  = ["vault.io"]
        file = false
        env  = false
      }

      vault {
        policies = ["minio"]
      }

      env {
        TZ = "America/Chicago"
      }

      template {
        data = <<EOH
MINIO_ROOT_USER="{{with secret "secret/data/minio"}}{{.Data.data.MINIO_ROOT_USER}}{{end}}"
MINIO_ROOT_PASSWORD="{{with secret "secret/data/minio"}}{{.Data.data.MINIO_ROOT_PASSWORD}}{{end}}"
EOH

        destination = "secrets/config.env"
        env         = true
      }

      config {
        image      = "pgsty/silo:RELEASE.2026-09-16T00-00-00Z"
        force_pull = true

        command = "server"

        args = [
          "--address",
          "0.0.0.0:9000",
          "--console-address",
          ":9001",
          "/data"
        ]

        ports = ["api", "http"]

        volumes = [
          "/volume1/minio:/data"
        ]
      }

      resources {
        memory = 1024
      }
    }
  }
}
