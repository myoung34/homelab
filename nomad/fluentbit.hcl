job "fluent-bit" {
  datacenters = ["dc1"]
  type        = "service"

  group "fluent-bit" {

    constraint {
      attribute = "${node.unique.name}"
      value     = "bigNASty"
    }

    # Host networking so in_tcp sees each Talos node's real address. Bridged,
    # every connection arrived from Docker's proxy (172.17.0.1). Same as
    # netbootxyz. The static ports below still reserve 5044-5046.
    network {
      mode = "host"

      port "syslog" {
        static = 5044
      }

      port "syslog2" {
        static = 5045
      }

      port "syslog3" {
        static = 5046
      }
    }

    task "fluent-bit" {
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

      template {
        data = <<EOH
DD_API_KEY="{{with secret "secret/data/datadog"}}{{.Data.data.DD_API_KEY}}{{end}}"
EOH

        destination = "secrets/config.env"
        env         = true
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
    Mode                udp
    Port                5045
    Parser              rfc3164
    Tag                 nas
    Buffer_Chunk_Size   32000
    Buffer_Max_Size     64000
    Receive_Buffer_Size 512000

[INPUT]
    Name                tcp
    Port                5046
    Format              json
    Tag                 talos
    # Talos' kernel/service log lines carry no hostname; record the sender
    # so Datadog monitors can name the node (e.g. Pi 5 macb TX stalls).
    Source_Address_Key  talos_node

[FILTER]
    Name  modify
    Match *
    Add Host bigNASty

[FILTER]
    Name  modify
    Match talos
    Add service talos

# talos_node arrives as "tcp://192.168.1.69:43122"; keep just the IP so it's
# a stable per-node key (the port changes on every reconnect).
[FILTER]
    Name  lua
    Match talos
    call  node_ip
    code  function node_ip(tag, ts, r) local a = r["talos_node"]; if a then local ip = string.match(a, "^%a+://%[?([^%]]-)%]?:%d+$"); if ip then r["talos_node"] = ip; return 1, ts, r end end; return 0, ts, r end

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

      config {
        image        = "fluent/fluent-bit:latest"
        force_pull   = true
        network_mode = "host"

        args = [
          "-c",
          "/opt/fluent-bit.conf"
        ]

        volumes = [
          "local/parsers.conf:/opt/parsers.conf",
          "local/fluent-bit.conf:/opt/fluent-bit.conf"
        ]
      }

      resources {
        cpu    = 300
        memory = 256
      }
    }
  }
}
