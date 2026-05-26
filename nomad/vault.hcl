job "vault" {
  datacenters = ["dc1"]

  group "vault" {

    network {
      port "http" {
        static = 8200
      }
    }

    task "vault" {
      driver = "docker"

      template {
        data = <<EOH
ui = true
disable_mlock = true

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = 1
}

storage "file" {
  path = "/vault/data"
}
EOH

        destination = "local/server.hcl"
      }

      config {
        image = "vault:1.13.3"

        entrypoint = ["vault"]

        command = "server"

        args = [
          "-config=/vault/config.d/server.hcl",
        ]

        ports = ["http"]

        volumes = [
          "/volume1/vault:/vault/data",
          "local/server.hcl:/vault/config.d/server.hcl",
        ]
      }

      resources {
        cpu    = 1000
        memory = 512
      }
    }
  }
}
