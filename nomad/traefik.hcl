job "traefik" {
  datacenters = ["dc1"]

  group "traefik" {
    network {
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
        ports = ["lb", "lbssl"]
        volumes = [
          "/var/run/docker.sock:/var/run/docker.sock",
        ]
        extra_hosts = [
          "bignasty:192.168.3.2",
        ]

        args = [
          "--accesslog",
          "--api.dashboard=false",
          "--api.insecure=true",
          "--providers.consulcatalog.endpoint.address=192.168.3.2:8500",
          "--providers.consulcatalog.defaultrule=Host(`{{ normalize .Name }}.consul.marcyoung.us`)",
          "--entryPoints.http.address=:80/tcp",
          "--entryPoints.https.address=:443/tcp",
          "--entryPoints.traefik.address=:8888/tcp",
        ]
        image = "traefik:v3.2"
        privileged = true
      }
    }
  }
}
