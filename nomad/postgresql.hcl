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
        # Postgres 16 plus pgvector and VectorChord, for immich
        # (k8s/prod/immich). The data dir is PG16: a new major needs a
        # pg_upgrade, not a tag bump (Renovate's v18/v19 bumps were never
        # applied). VectorChord has no PG19 build.
        image      = "ghcr.io/immich-app/postgres:16-vectorchord1.1.1-pgvector0.8.7"
        force_pull = true

        entrypoint = ["docker-entrypoint.sh"]
        args       = ["postgres", "-c", "shared_preload_libraries=vchord.so"]

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
