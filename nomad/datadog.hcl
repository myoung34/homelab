job "datadog" {
  datacenters = ["dc1"]
  type        = "service"

  group "datadog" {

    constraint {
      attribute = "${node.unique.name}"
      value     = "bigNASty"
    }

    network {
      port "dd_statsd" {
        static = 8125
      }

      port "apm" {
        static = 8126
      }
    }

    task "datadog" {
      driver = "docker"

      identity {
        name = "vault_default"
        aud  = ["vault.io"]
        file = false
        env  = false
      }

      vault {
        disable_file = true
        policies     = ["datadog"]
      }

      env {
        TZ                                   = "America/Chicago"
        DD_PROCESS_AGENT_ENABLED             = "true"
        DD_APM_ENABLED                       = "true"
        DD_LOGS_ENABLED                      = "true"
        DD_LOGS_CONFIG_CONTAINER_COLLECT_ALL = "true"
        DD_DOGSTATSD_NON_LOCAL_TRAFFIC       = "true"
        DD_LOGS_CONFIG_OPEN_FILES_LIMIT      = "10000"
      }

      template {
        data = <<EOH
DD_API_KEY="{{with secret "secret/data/datadog"}}{{.Data.data.DD_API_KEY}}{{end}}"
SLACK_WEBHOOK="{{with secret "secret/data/datadog"}}{{.Data.data.SLACK_WEBHOOK}}{{end}}"
EOH

        destination = "secrets/config.env"
        env         = true
      }

      template {
        data = <<EOH
logs:
  - type: file
    path: /opt/logs/**/*.log
    exclude_paths:
      - /opt/logs/ecs/ecs-volume-plugin.log
      - /opt/logs/upstart/*.log
      - /opt/logs/Docker/docker.log
    service: nomad
    source: bigNASty

  - type: file
    path: /opt/logs/*.log
    service: nomad
    source: bigNASty
EOH

        destination = "local/log.d/conf.yaml"
      }

      template {
        data = <<EOH
logs:
  - type: file
    path: /opt/nomad-logs/nomad.log
    source: custom
    service: nomad
EOH

        destination = "local/custom_log_collection.d/conf.yaml"
      }

      template {
        data = <<EOH
init_config:

instances:
  - api_url: http://192.168.3.2:8200/v1
    no_token: true
EOH

        destination = "local/vault.d/conf.yaml"
      }

      template {
        data = <<EOH
# loader: core (Go). The python loader crashes on every run on the
# agent's Python 3.13 ("There is no current event loop"), so nothing
# below was being collected. Core also decodes Synology's Opaque-float
# UPS values that broke the python loader with "embedded null
# character" (DataDog/integrations-core#10899) - the reason for the old
# Zapier-based synology-ups-datadog job. Core only honours the
# `symbol:` syntax; the legacy top-level OID/name form is silently
# ignored.
init_config:
  loader: core

instances:
  - ip_address: 192.168.3.2
    snmp_version: 2
    port: 161
    community_string: home
    min_collection_interval: 60

    metric_tags:
      - tag: snmp_host
        symbol:
          OID: 1.3.6.1.2.1.1.5.0
          name: sysName

      # OL = on line, OB = on battery, LB = low battery (NUT status).
      - tag: ups_status
        symbol:
          OID: 1.3.6.1.4.1.6574.4.2.1.0
          name: upsInfoStatus

    metrics:
      - symbol:
          OID: 1.3.6.1.4.1.6574.4.3.1.1.0
          name: upsBatteryChargeValue

      - symbol:
          OID: 1.3.6.1.4.1.6574.4.3.6.1.0
          name: upsBatteryRuntimeValue

      - symbol:
          OID: 1.3.6.1.4.1.6574.4.2.12.1.0
          name: upsInfoLoadValue

      - symbol:
          OID: 1.3.6.1.2.1.1.3.0
          name: uptime

      - symbol:
          OID: 1.3.6.1.4.1.2021.11.9.0
          name: ssCpuUser

      - symbol:
          OID: 1.3.6.1.4.1.2021.11.10.0
          name: ssCpuSystem

      - symbol:
          OID: 1.3.6.1.4.1.2021.11.11.0
          name: laCpuIdle

      - symbol:
          OID: 1.3.6.1.4.1.2021.10.1.5.1
          name: laLoad.1

      - symbol:
          OID: 1.3.6.1.4.1.6574.1.2.0
          name: cpuTemp

      - symbol:
          OID: 1.3.6.1.4.1.2021.4.3.0
          name: swapTotal

      - symbol:
          OID: 1.3.6.1.4.1.2021.4.4.0
          name: swapFree

      - symbol:
          OID: 1.3.6.1.4.1.2021.4.5.0
          name: memoryTotal

      - symbol:
          OID: 1.3.6.1.4.1.2021.4.6.0
          name: memoryUsed

      - symbol:
          OID: 1.3.6.1.4.1.2021.4.11.0
          name: memoryFree

      - symbol:
          OID: 1.3.6.1.4.1.2021.4.15.0
          name: memoryCached

      - MIB: IF-MIB
        table:
          OID: 1.3.6.1.2.1.2.2
          name: ifTable
        symbols:
          - OID: 1.3.6.1.2.1.2.2.1.10
            name: ifInOctets
          - OID: 1.3.6.1.2.1.2.2.1.16
            name: ifOutOctets
        metric_tags:
          - tag: interface
            column:
              OID: 1.3.6.1.2.1.2.2.1.2
              name: ifDescr
EOH

        destination = "local/snmp.d/conf.yaml"
      }

      config {
        image      = "datadog/agent:7"
        force_pull = true
        privileged = true

        ports = [
          "dd_statsd",
          "apm"
        ]

        volumes = [
          "local/vault.d/conf.yaml:/etc/datadog-agent/conf.d/vault.d/conf.yaml",
          "local/custom_log_collection.d/conf.yaml:/etc/datadog-agent/conf.d/custom_log_collection.d/conf.yaml",
          "local/log.d/conf.yaml:/etc/datadog-agent/conf.d/log.d/conf.yaml",
          "local/snmp.d/conf.yaml:/etc/datadog-agent/conf.d/snmp.d/conf.yaml"
        ]

        mounts = [
          {
            type     = "bind"
            source   = "/var/log"
            target   = "/opt/logs"
            readonly = false
          },
          {
            type     = "bind"
            source   = "/volume1/@appdata/nomad/log"
            target   = "/opt/nomad-logs"
            readonly = true
          },
          {
            type     = "bind"
            source   = "/volume1/@appdata/datadog/run"
            target   = "/opt/datadog-agent/run"
            readonly = false
          },
          {
            type     = "bind"
            source   = "/sys/fs/cgroup/"
            target   = "/host/sys/fs/cgroup/"
            readonly = true
          },
          {
            type     = "bind"
            source   = "/proc"
            target   = "/host/proc"
            readonly = true
          },
          {
            type     = "bind"
            source   = "/var/run/docker.sock"
            target   = "/var/run/docker.sock"
            readonly = true
          },
          {
            type     = "bind"
            source   = "/etc/passwd"
            target   = "/etc/passwd"
            readonly = true
          },
          {
            type     = "bind"
            source   = "/volume1/@docker/containers"
            target   = "/var/lib/docker/containers"
            readonly = true
          },
        ]
      }

      resources {
        cpu    = 2000
        memory = 2048
      }
    }
  }
}
