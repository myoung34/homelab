job "obsidian-render" {
  type = "batch"
  datacenters = ["dc1"]
  periodic {
    cron = "0 4 * * *"
    prohibit_overlap = true
  }
  group "obsidian" {
    task "render" {
      driver = "docker"

      config {
        image = "alpine:latest"
        command = "sh"
        args = ["-c", "( apk add -U git nodejs npm; git clone https://github.com/jackyzha0/quartz.git; cd quartz; npm i; git config --global --add safe.directory /opt/obsidian.git/.git; rm -rf content; git clone /opt/obsidian.git .content -b main; mv .content/Marc content/; npx quartz build; cp -r public/* /opt/obsidian )"]
        volumes = [
          "/volume1/minio/obsidian-rendered:/opt/obsidian",
          "/volume1/minio/obsidian:/opt/obsidian.git",
        ]
      }
    }
  }
}
