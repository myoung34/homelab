job "mosquitto" {
  datacenters = ["dc1"]

  group "mosquitto" {
    network {
      port "mqtt" {
        static = "1883"
      }
    }
    task "mosquitto" {

      driver = "docker"
      resources {
        memory = 1024
      }

      template {
        data = <<EOH
        per_listener_settings false
        user root
        listener 1883
        allow_anonymous true
        EOH
        destination = "local/mosquittoconf"
      }

      service {
        name = "mosquitto"
        port = "mqtt"
        tags = [
          "traefik.tcp.routers.mosquitto_http.entrypoints=mqtt",
          "traefik.tcp.routers.http.rule=Host(`mosquitto.consul.marcyoung.us`)",
        ]
      }
      config {
        ports = ["mqtt"]
        image = "eclipse-mosquitto:2.0.18"
        force_pull = true
        volumes = [
          "local/mosquittoconf:/mosquitto/config/mosquitto.conf",
        ]
      }
    }
  }
}
