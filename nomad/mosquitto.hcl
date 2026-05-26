job "mosquitto" {
  datacenters = ["dc1"]
  type        = "service"

  group "mosquitto" {

    constraint {
      attribute = "${node.unique.name}"
      value     = "bigNASty"
    }

    network {
      port "mqtt" {
        static = 1883
      }
    }

    task "mosquitto" {
      driver = "docker"

      template {
        data = <<EOH
per_listener_settings false
user root

listener 1883

allow_anonymous true
EOH

        destination = "local/mosquitto.conf"
      }

      service {
        provider = "nomad"

        name = "mosquitto"
        port = "mqtt"
      }

      config {
        image      = "eclipse-mosquitto:2.0.20"
        force_pull = true

        ports = [
          "mqtt"
        ]

        volumes = [
          "local/mosquitto.conf:/mosquitto/config/mosquitto.conf"
        ]
      }

      resources {
        memory = 1024
      }
    }
  }
}
