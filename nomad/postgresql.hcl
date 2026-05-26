job "postgresql" {
  datacenters = ["dc1"]

  group "postgresql" {

    network {
      port "postgresql" {
        static = 5432
      }
    }

    task "postgresql" {
      driver = "docker"

      # Explicit workload identity for Vault
      identity {
        name = "vault_default"
        aud  = ["vault.io"]
        file = false
        env  = false
      }

      vault {
        policies = ["nomad-server"]
      }

      template {
        data = <<EOH
POSTGRES_USER="{{with secret "secret/data/postgresql"}}{{.Data.data.admin_user}}{{end}}"
POSTGRES_PASSWORD="{{with secret "secret/data/postgresql"}}{{.Data.data.admin_password}}{{end}}"
EOH

        destination = "secrets/config.env"
        env         = true
      }

      config {
        image      = "postgres:16-bookworm"
        force_pull = true

        entrypoint = ["docker-entrypoint.sh"]
        args       = ["postgres"]

        ports = ["postgresql"]

        volumes = [
          "/volume1/postgresql/data:/var/lib/postgresql/data"
        ]
      }

      user = "999"

      resources {
        memory = 2048
      }
    }
  }
}
