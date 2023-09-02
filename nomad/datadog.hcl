job "datadog" {
  datacenters = ["dc1"]
  type = "system"

  group "datadog" {
    network {
      port "dd_statsd" {
        static = "8125"
      }
      port "apm" {
        static = "8126"
      }
    }

    task "datadog" {
      driver = "docker"

      vault {
        policies = ["datadog"]
      }

      env {
        TZ = "America/Chicago"
        DD_PROCESS_AGENT_ENABLED = "true"
        DD_APM_ENABLED = "true"
        DD_LOGS_ENABLED = "true"
        DD_LOGS_CONFIG_CONTAINER_COLLECT_ALL = "true"
        DD_DOGSTATSD_NON_LOCAL_TRAFFIC = "true"
        DD_LOGS_CONFIG_OPEN_FILES_LIMIT = "10000"
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
        init_config:
          loader: python
          oid_batch_size: 60
          profiles:
            generic:
              definition_file: _generic-host-resources.yaml

        instances:
          - ip_address: 192.168.3.2
            snmp_version: 2
            port: 161
            community_string: home
            min_collection_interval: 60
            enforce_mib_constraints: false
            metric_tags:
              - OID: .1.3.6.1.2.1.1.5.0
                tag: snmp_host
                symbol: sysName
              - OID: .1.3.6.1.2.1.1.5.0
                tag: host
                symbol: sysName
            metrics: # https://global.download.synology.com/download/Document/Software/DeveloperGuide/Firmware/DSM/All/enu/Synology_DiskStation_MIB_Guide.pdf
              - OID: .1.3.6.1.4.1.6574.4.3.6.1
                name: upsBatteryRuntimeValue
            #  - OID: .1.3.6.1.4.1.6574.4.3.1.1.0
            #    name: upsBatteryChargeValue
            #    #extract_value: '.*(\d+)\.'
            #    #forced_type: percent
            #  - OID: .1.3.6.1.4.1.6574.4.2.12.1
            #    name: upsInfoLoadValue
            #  - OID: .1.3.6.1.4.1.6574.4.2.1
            #    name: upsInfoStatus
              - OID: .1.3.6.1.2.1.1.3.0
                name: uptime
              - OID: .1.3.6.1.4.1.2021.11.9.0
                name: ssCpuUser
              - OID: .1.3.6.1.4.1.2021.11.10.0
                name: ssCpuSystem
              - OID: .1.3.6.1.4.1.2021.11.11.0
                name: laCpuIdle
              - OID: .1.3.6.1.4.1.2021.10.1.5.1
                name: laLoad.1
              - OID: .1.3.6.1.4.1.6574.1.2.0
                name: cpuTemp
              - OID: .1.3.6.1.4.1.2021.4.3.0
                name: swapTotal
              - OID:  .1.3.6.1.4.1.2021.4.4.0
                name: swapFree
              - OID: .1.3.6.1.4.1.2021.4.5.0
                name: memoryTotal
              - OID: .1.3.6.1.4.1.2021.4.6.0
                name: memoryUsed
              - OID: .1.3.6.1.4.1.2021.4.11.0
                name: memoryFree
              - OID: .1.3.6.1.4.1.2021.4.15.0
                name: memoryCached
              - MIB: IF-MIB
                table: ifTable
                symbols:
                  - ifInOctets
                  - ifOutOctets
                metric_tags:
                  - tag: interface
                    column: ifDescr

        EOH
        destination = "local/snmp.d/conf.yaml"
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
            path: /var/log/nomad.log
            source: custom
            service: nomad
          - type: file
            path: /var/log/consul.log
            source: custom
            service: consul
        EOH
        destination = "local/custom_log_collection.d/conf.yaml"
      }
      template {
        data = <<EOH
        init_config:
        instances:
        - url: http://bignasty:8500
        EOH
        destination = "local/consul.d/conf.yaml"
      }

      config {
        ports = ["dd_statsd", "apm"]
        force_pull = true
        #image = "datadog/agent:7.29.1"
        image = "datadog/agent:7"
        volumes = [
          "local/consul.d/conf.yaml:/etc/datadog-agent/conf.d/consul.d/conf.yaml",
          "local/custom_log_collection.d/conf.yaml:/etc/datadog-agent/conf.d/custom_log_collection.d/conf.yaml",
          "local/log.d/conf.yaml:/etc/datadog-agent/conf.d/log.d/conf.yaml",
          "local/snmp.d/conf.yaml:/etc/datadog-agent/conf.d/snmp.d/conf.yaml",
        ]
        mounts = [
          {
            type = "bind"
              source = "/var/log"
              target = "/opt/logs"
              readonly = false
          },
          {
            type = "bind"
              source = "/sys/fs/cgroup/"
              target = "/host/sys/fs/cgroup/"
              readonly = true
          },
          {
            type = "bind"
              source = "/proc"
              target = "/host/proc"
              readonly = true
          },
          {
            type = "bind"
              source = "/var/run/docker.sock"
              target = "/var/run/docker.sock"
              readonly = true
          },
          {
            type = "bind"
              source = "/etc/passwd"
              target = "/etc/passwd"
              readonly = true
          }
        ]
      }
      resources {
        cpu    = 2000
        memory = 1024
      }
    }
  }
}
