job "minio" {
  datacenters = ["dc1"]

  group "minio" {
    network {
      port "api" {
        static = "9000"
      }
      port "http" {
        static = "9001"
      }
    }
    task "minio" {

      driver = "docker"
      resources {
        memory = 1024
      }

      env {
        TZ = "America/Chicago"
      }

      vault {
        policies = ["minio"]
      }

      template {
        data = <<EOH
          MINIO_ROOT_USER="{{with secret "secret/data/minio"}}{{.Data.data.MINIO_ROOT_USER}}{{end}}"
          MINIO_ROOT_PASSWORD="{{with secret "secret/data/minio"}}{{.Data.data.MINIO_ROOT_PASSWORD}}{{end}}"
        EOH

        destination = "secrets/config.env"
        env         = true
      }

      service {
        name = "minio"
        port = "http"
        tags = [
          "traefik.http.routers.minio_https.entrypoints=https",
          "traefik.http.routers.minio_https.tls=true",

          "traefik.http.routers.minio_http.entrypoints=api",
          "traefik.http.routers.http.rule=Host(`minio.consul.marcyoung.us`)",
        ]
      }
      config {
        ports = ["api", "http"]
        command = "server"
        args = [
          "--address",
          "0.0.0.0:9000",
          "--console-address",
          ":9001",
          "/data"
        ]
        image = "minio/minio:latest"

        force_pull = true
        volumes = [
          "/volume1/minio:/data"
        ]
      }
    }
  }
}
