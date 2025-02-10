job "obsidian" {
  datacenters = ["dc1"]

  group "obsidian" {
    network {
      port "http" {
        host_network = "tailscale"
        static = "8080"
      }
    }
    task "obsidian" {

      driver = "docker"
      template {
        data = <<EOH
          server {
              listen       8080;
              server_name  localhost;

              root   /usr/share/nginx/html;
              index  index.html index.htm;

              location / {
                # force it to try to add the .html extension
                try_files $uri $uri/ @htmlext;
              }

              location @htmlext {
                  rewrite ^(.*)$ $1.html last;
              }

              error_page   500 502 503 504  /50x.html;
              location = /50x.html {
              }
          }
        EOH
        destination = "custom/default.conf"
      }

      service {
        name = "obsidian"
        port = "http"
        tags = [
          "traefik.http.routers.minio_https.entrypoints=https",
          "traefik.http.routers.minio_https.tls=true",
          "traefik.http.routers.minio_http.entrypoints=api",
          "traefik.http.routers.http.rule=Host(`obsidian.consul.marcyoung.us`)",
        ]
      }

      config {
        ports = ["http"]
        image = "nginxinc/nginx-unprivileged"

        force_pull = true
        volumes = [
          "custom/default.conf:/etc/nginx/conf.d/default.conf",
          "/volume1/minio/obsidian-rendered:/usr/share/nginx/html",
        ]
      }
    }
  }
}
