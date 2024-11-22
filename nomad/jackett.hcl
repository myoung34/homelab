job "jackett" {
  datacenters = ["dc1"]

  group "jackett" {
    network {
      port "http" {
        static = "9117"
      }
    }
    task "jackett" {
      driver = "docker"

      env {
        TZ = "America/Chicago"
        PGID = "100"
        PUID = "1026"
      }

      service {
        name = "jackett"
        port = "http"
        tags = [
          "traefik.http.routers.jackett_https.entrypoints=https",
          "traefik.http.routers.jackett_https.tls=true",
          "traefik.http.routers.jackett_http.entrypoints=http",
          "traefik.http.routers.jackett_http.middlewares=jackett_https_redirect",
          "traefik.http.middlewares.jackett_https_redirect.redirectscheme.scheme=https",
        ]
      }

      config {
        ports = ["http"]
        image = "linuxserver/jackett:latest"
        force_pull = true
        volumes = [
          "/volume1/torrent/jackett/downloads:/downloads",
          "/volume1/torrent/jackett/config:/config",
        ]
      }
    }
  }
}
