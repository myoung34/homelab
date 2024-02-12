job "postgresql" {
  datacenters = ["dc1"]

  group "postgresql" {
    network {
      port "postgresql" {
        static = "5432"
      }
    }
    task "postgresql" {
      driver = "docker"
      vault {
        policies = ["postgresql"]
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
        ports = ["postgresql"]
        image = "postgres:16-bookworm"
        force_pull = true
        entrypoint = ["docker-entrypoint.sh"]
        args = ["postgres"]

        volumes = [
          "/volume1/postgresql/data:/var/lib/postgresql/data" # 999:999
        ]
      }
      user = "999"
      resources {
        memory = 2048
      }
    }
  }
}
