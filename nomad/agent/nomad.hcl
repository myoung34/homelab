# Nomad agent config for bigNASty. Not a job file.
# Deploy by hand: copy to /var/packages/nomad/shares/nomad/etc/nomad.d/nomad.hcl,
# then `sudo synopkg restart nomad` (running allocs are reattached, not restarted).
data_dir = "/volume1/@appdata/nomad/data"
bind_addr = "0.0.0.0" # the default

advertise {
  # Defaults to the first private IP address.
}

limits {
  http_max_conns_per_client = 0
}

#workload_identity {
#  enabled = false
#}

server {
  enabled          = true
  bootstrap_expect = 1
  # Single node: a UDM Pro firmware reboot drops eth0 for minutes. The 10s
  # default marked the node down, replaced every alloc, and sealed Vault.
  heartbeat_grace  = "10m"

  oidc_issuer = "http://192.168.3.2:4646"
  #workload_identity {
  #  issuer = "http://192.168.3.2:4646"
  #}
}

#consul {
#  address          = "192.168.3.2:8500"
#  server_auto_join = true
#  client_auto_join = true
#  verify_ssl       = false
#}

client {
  enabled           = true
  network_interface = "eth0"
  gc_max_allocs     = 400

  options = {
    "docker.volumes.enabled"    = "True"
    "docker.privileged.enabled" = "True"
  }

  host_network "tailscale" {
    cidr = "100.64.0.0/10"
  }
}

plugin "docker" {
  config {
    allow_caps = ["IPC_LOCK"]
	allow_privileged = true
	volumes {
	  enabled = true
    }
  }
}

vault {
  enabled          = true
  tls_skip_verify  = true
  address          = "http://192.168.3.2:8200"
}

plugin "raw_exec" {
  config {
    enabled = true
  }
}

telemetry {
  publish_allocation_metrics = true
  publish_node_metrics       = true
  datadog_address = "192.168.3.2:8125"
  disable_hostname = true
  collection_interval = "10s"
}

log_level = "DEBUG"
log_file  = "/volume1/@appdata/nomad/log/nomad.log"
log_rotate_bytes = 104857600
log_rotate_duration = "24h"
log_rotate_max_files = 10
