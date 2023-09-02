job "traefik" {
  datacenters = ["dc1"]

  group "traefik" {
    network {
      port "dash" {
        static = 8888
      }
      port "lb" {
        static = 80
      }
      port "lbssl" {
        static = 443
      }
    }
    task "traefik" {
      driver = "docker"

      config {
        ports = ["lb", "lbssl", "dash"]
        volumes = [
          "/var/run/docker.sock:/var/run/docker.sock",
        ]

        args = [
          "--accesslog",
          "--api.dashboard=true",
          "--api.insecure=true",
          "--providers.consulcatalog.endpoint.address=192.168.3.2:8500",
          "--providers.consulcatalog.defaultrule=Host(`{{ normalize .Name }}.service.consul`)",
          "--entryPoints.http.address=:80/tcp",
          "--entryPoints.https.address=:443/tcp",
          "--entryPoints.traefik.address=:8888/tcp",
        ]
        image = "traefik:v2.3"
        privileged = true
      }
    }
  }
}
