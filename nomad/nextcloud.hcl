job "nextcloud" {
  datacenters = ["dc1"]

  group "nextcloud" {
    network {
      port "nc_http" {
        static = "8000"
      }

      port "redis" {
        static = "6379"
      }

      port "psql" {
        static = "5432"
      }
    }
    task "redis" {

      driver = "docker"
      env {
        TZ = "America/Chicago"
      }

      config {
        ports = ["redis"]
        image = "redis:latest"

      }
    }
    task "nextcloud" {
      driver = "docker"
      vault {
        policies = ["nextcloud"]
      }
      env {
        POSTGRES_HOST = "192.168.3.2:5432"
        REDIS_HOST = "192.168.3.2"
      }

      template {
        data = <<EOH
          POSTGRES_USER="{{with secret "secret/data/nextcloud"}}{{.Data.data.POSTGRES_USER}}{{end}}"
          POSTGRES_PASSWORD="{{with secret "secret/data/nextcloud"}}{{.Data.data.POSTGRES_PASSWORD}}{{end}}"
        EOH
        destination = "secrets/config.env"
        env         = true
      }

      service {
        name = "nextcloud"
        port = "nc_http"
        tags = [
          "traefik.http.routers.nextcloud_https.entrypoints=https",
          "traefik.http.routers.nextcloud_https.tls=true",
          "traefik.http.routers.nextcloud_http.entrypoints=http",
          "traefik.http.routers.nextcloud_http.middlewares=nextcloud_https_redirect",
          "traefik.http.middlewares.nextcloud_https_redirect.redirectscheme.scheme=https",
        ]
      }
      config {
        ports = ["nc_http"]
        image = "nextcloud:17.0.9"


        volumes = [
          "/volume1/nextcloud/nextcloud:/var/www/html"
        ]
      }
    }
  }
}
