job "utorrent" {
  datacenters = ["dc1"]

  group "utorrent" {
    network {
      port "http" {
        static = "8080"
      }
      port "tcp" {
        static = "6881"
      }
    }
    task "utorrent" {
      driver = "docker"

      env {
        TZ = "America/Chicago"
        UID = 1026
        GID = 100
        dir_active = "/utorrent/data"
        dir_completed = "/utorrent/data"
        dir_root = "/utorrent/data"
      }

      service {
        name = "utorrent"
        port = "http"
        tags = [
          "traefik.http.routers.utorrent_https.entrypoints=https",
          "traefik.http.routers.utorrent_https.tls=true",
          "traefik.http.routers.utorrent_http.entrypoints=http",
          "traefik.http.routers.utorrent_http.middlewares=utorrent_https_redirect",
          "traefik.http.middlewares.utorrent_https_redirect.redirectscheme.scheme=https",
        ]
      }

      config {
        ports = ["http", "tcp"]
        image = "ekho/utorrent"

        command = "/utorrent/utserver"
        args = [
          "-settingspath",
          "/utorrent/settings",
          "-configfile",
          "/utorrent/utserver.conf",
          "-logfile",
          "/utorrent/logs/server.log",
        ]
        volumes = [
          "/volume1/torrent/utorrent/data:/utorrent/data",
          "/volume1/torrent/utorrent/settings:/utorrent/settings",
          "/volume1/torrent/utorrent/downloads:/utorrent/downloads",
          "/volume1/torrent/utorrent/logs:/utorrent/logs",
          "/volume1/torrent/utorrent/torrents:/utorrent/torrents",
          "/volume1/torrent/utorrent/autoload:/utorrent/autoload",
          "/volume1/torrent/utorrent/utserver.conf:/utorrent/utserver.conf",
        ]
      }
      resources {

      }
    }
  }
}
