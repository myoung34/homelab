job "influxdb" {
  datacenters = ["dc1"]

  group "influxdb" {
    network {
      port "http" {
        static = "8086"
      }
    }
    task "influxdb" {
      driver = "docker"

      template {
        data = <<EOH
          INFLUXDB_ADMIN_USER="{{with secret "secret/data/influxdb"}}{{.Data.data.INFLUXDB_ADMIN_USERMYSQL_ROOT_PASSWORD}}{{end}}"
          INFLUXDB_ADMIN_PASSWORD="{{with secret "secret/data/influxdb"}}{{.Data.data.INFLUXDB_ADMIN_PASSWORD}}{{end}}"
        EOH
        destination = "secrets/config.env"
        env         = true
      }
      env {
        INFLUXDB_DB = "wat"
        INFLUXDB_HTTP_AUTH_ENABLED = "true"
        INFLUXDB_HTTP_FLUX_ENABLED = "true"
      }

      service {
        name = "influxdb"
        port = "http"
        tags = [
          "traefik.http.routers.influxdb_http.entrypoints=http",
        ]
      }

      config {
        ports = ["http"]
        image = "influxdb:1.8-alpine"
        force_pull = true
      }
    }
  }
}


# curl -XPOST localhost:8086/api/v2/query -sS \
#   -H 'Accept:application/csv' \
#   -H 'Content-type:application/vnd.flux' \
#   -H 'Authorization: Token changeme:changeme' \
#   -d 'from(bucket:"wat")
#        |> range(start:-5m)'
