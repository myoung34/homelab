job "mysql" {
  datacenters = ["dc1"]

  group "mysql" {
    network {
      port "mysql" {
        static = "3306"
      }
    }
    task "mysql" {
      driver = "docker"
      vault {
        policies = ["mysql"]
      }
      template {
        data = <<EOH
          MYSQL_ROOT_PASSWORD="{{with secret "secret/data/mysql"}}{{.Data.data.MYSQL_ROOT_PASSWORD}}{{end}}"
          MYSQL_USER="{{with secret "secret/data/mysql"}}{{.Data.data.MYSQL_USER}}{{end}}"
          MYSQL_PASSWORD="{{with secret "secret/data/mysql"}}{{.Data.data.MYSQL_PASSWORD}}{{end}}"
          MYSQL_DATABASE="k3s"
        EOH
        destination = "secrets/config.env"
        env         = true
      }

      config {
        ports = ["mysql"]
        image = "mysql:5"
        force_pull = true

        volumes = [
          "/volume1/mysql/data:/var/lib/mysql"
        ]
      }
    }
  }
}
