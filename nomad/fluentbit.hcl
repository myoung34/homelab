job "fluent-bit" {
  datacenters = ["dc1"]

  group "fluent-bit" {
    network {
      port "syslog" {
        static = "5044"
      }
      port "syslog2" {
        static = "5045"
      }
    }
    task "fluent-bit" {

      driver = "docker"

      vault {
        policies = ["datadog"]
      }

      #resources {
      #  cpu    = 300
      #  memory = 256
      #}

      env {
      }


      template {
        data = <<EOH
[PARSER]
    Name        rfc3164
    Format      regex
    Regex       ^\<(?<pri>[0-9]{1,5})\>(?<date>[a-zA-Z]{3}  [0-9]{1,2} [0-9]{1,2}:[0-9]{1,2}:[0-9]{1,2})? ?(?<message>.*)
    Time_Key    time
    Time_Keep   On
        EOH
        destination = "local/parsers.conf"
      }
      template {
        data = <<EOH
[SERVICE]
    Flush        1
    Parsers_File /opt/parsers.conf

[INPUT]
    Name                syslog
    Mode                udp
    Port                5044
    Parser              rfc3164
    Tag                 unifi
    Buffer_Chunk_Size   32000
    Buffer_Max_Size     64000
    Receive_Buffer_Size 512000

[INPUT]
    Name                syslog
    Tag                 nas
    Mode                udp
    Port                5045
    Parser              rfc3164
    Buffer_Chunk_Size   32000
    Buffer_Max_Size     64000
    Receive_Buffer_Size 512000
[FILTER]
    Name  modify
    Match *
    Add Host bigNASty
[FILTER]
    Name  modify
    Match unifi
    Add service unifi
[FILTER]
    Name  modify
    Match nas
    Add service synology
[OUTPUT]
    Name           datadog
    Match          *
    Host           http-intake.logs.datadoghq.com
    TLS            on
    apikey         ${DD_API_KEY}
    dd_source      bigNASty
    dd_tags        env:home
        EOH
        destination = "local/fluent-bit.conf"
      }

      template {
        data = <<EOH
          DD_API_KEY="{{with secret "secret/data/datadog"}}{{.Data.data.DD_API_KEY}}{{end}}"
        EOH

        destination = "secrets/config.env"
        env         = true
      }

      config {
        ports = ["syslog", "syslog2"]
        image = "fluent/fluent-bit:latest"
        args = [
          "-c",
          "/opt/fluent-bit.conf"
        ]

        force_pull = true
        volumes = [
          "local/parsers.conf:/opt/parsers.conf",
          "local/fluent-bit.conf:/opt/fluent-bit.conf",
        ]
      }
    }
  }
}
