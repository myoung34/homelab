job "radarr" {
  datacenters = ["dc1"]

  group "radarr" {
    network {
      port "http" {
        static = "7878"
      }
    }
    task "radarr" {
      driver = "docker"

      env {
        TZ = "America/Chicago"
        PGID = "100"
        PUID = "1026"
      }

      service {
        name = "radarr"
        port = "http"
        tags = [
          "traefik.http.routers.radarr_https.entrypoints=https",
          "traefik.http.routers.radarr_https.tls=true",
          "traefik.http.routers.radarr_http.entrypoints=http",
          "traefik.http.routers.radarr_http.middlewares=radarr_https_redirect",
          "traefik.http.middlewares.radarr_https_redirect.redirectscheme.scheme=https",
        ]
      }
      config {
        ports = ["http"]
        force_pull = true
        image = "linuxserver/radarr:latest"
        volumes = [
          "/volume1/Movies:/movies",
          "/volume1/torrent/utorrent:/utorrent",
          "/volume1/torrent/radarr/config:/config",
        ]
      }
      resources {

      }
    }
  }
}
