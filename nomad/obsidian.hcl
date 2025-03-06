job "obsidian" {
  type = "batch"
  datacenters = ["dc1"]
  periodic {
    cron = "* 8 * * *"
    prohibit_overlap = true
  }
  group "obsidian" {
    task "render" {
      driver = "docker"

      vault {
        policies = ["obsidian"]
      }
      template {
        data = <<EOH
          AWS_ACCESS_KEY_ID="{{with secret "secret/data/obsidian"}}{{.Data.data.AWS_ACCESS_KEY_ID}}{{end}}"
          AWS_SECRET_ACCESS_KEY="{{with secret "secret/data/obsidian"}}{{.Data.data.AWS_SECRET_ACCESS_KEY}}{{end}}"
        EOH
        destination = "secrets/config.env"
        env         = true
      }

      config {
        image = "alpine:latest"
        command = "sh"
        args = ["-c", "( apk add -U aws-cli git nodejs npm; git clone https://github.com/jackyzha0/quartz.git; cd quartz; npm i; git config --global --add safe.directory /opt/obsidian.git/.git; rm -rf content; git clone /opt/obsidian.git .content -b main; mv .content/Marc content/; sed -i.bak 's/Plugin.ObsidianFlavoredMarkdown.*/Plugin.ObsidianFlavoredMarkdown({ enableInHtmlEmbed: false, parseTags: true}),/g' quartz.config.ts; npx quartz build; find public/ -type f -name '*.html' ! -name 'index.html' | while read -r file; do mv $file $$${file%.html}; done; mkdir /opt/obsidian; cp -r public/* /opt/obsidian; cd /opt/obsidian; aws configure set default.s3.signature_version s3v4; aws s3 rm --endpoint-url http://minio.consul.marcyoung.us:9000 s3://obsidian-rendered/ --recursive; ls -alh; aws --endpoint-url http://minio.consul.marcyoung.us:9000 s3 sync . s3://obsidian-rendered/; )"]
        volumes = [
          "/volume1/minio/obsidian:/opt/obsidian.git",
        ]
      }
    }
  }
}
