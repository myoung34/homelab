job "synology-ups-datadog" {
  type = "batch"
  datacenters = ["dc1"]
  periodic {
    cron = "* * * * *"
    prohibit_overlap = true
  }
  group "ups" {
    task "ups" {
      driver = "docker"

      vault {
        policies = ["datadog"]
      }

      config {
        image = "myoung34/synology-ups-datadog:latest"
      }
      template {
        data = <<EOH
          HOOK_URL="{{with secret "secret/data/datadog"}}{{.Data.data.UPS_HOOK_URL}}{{end}}"
        EOH
        destination = "secrets/config.env"
        env         = true
      }
    }
  }
}
