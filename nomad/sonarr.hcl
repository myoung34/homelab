job "sonarr" {
  datacenters = ["dc1"]

  group "sonarr" {
    network {
      port "http" {
        static = "8989"
      }
    }
    task "sonarr" {
      driver = "docker"

      env {
        TZ = "America/Chicago"
        PGID = "100"
        PUID = "1026"
      }

      service {
        name = "sonarr"
        port = "http"
        tags = [
          "traefik.http.routers.sonarr_https.entrypoints=https",
          "traefik.http.routers.sonarr_https.tls=true",
          "traefik.http.routers.sonarr_http.entrypoints=http",
          "traefik.http.routers.sonarr_http.middlewares=sonarr_https_redirect",
          "traefik.http.middlewares.sonarr_https_redirect.redirectscheme.scheme=https",
        ]
      }
      config {
        ports = ["http"]
        force_pull = true
        image = "linuxserver/sonarr:latest"
        volumes = [
          "/volume1/TV:/tv",
          "/volume1/torrent/utorrent:/utorrent",
          "/volume1/torrent/sonarr/config:/config",
        ]
      }
      resources {

      }
    }
  }
}
