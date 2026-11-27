# One "logs stopped" monitor per stream, like talos_logs_stopped_arriving_in_datadog.
# Log-based monitors go quiet, not red, when their input dies: Synology's
# login monitor sat dead for 7+ days. Ungrouped on purpose: a grouped "< 1"
# monitor has no group to alert on once a stream is gone entirely.
#
# Windows sit well under each stream's quietest stretch over 7 days
# (2026-11-27): unifi >= 782 lines/30m, k8s containers >= 73/30m, NAS log
# files >= 110/1h.
#
# Synology syslog (service:synology) gets one once DSM Log Sending is on;
# today it would alert from the start.
locals {
  logs_stopped = {
    unifi = {
      name   = "UniFi"
      query  = "service:unifi"
      window = "30m"
      path   = "UniFi syslog -> fluent-bit :5044 (Nomad on bigNASty, nomad/fluentbit.hcl) -> Datadog. Check `nomad job status fluent-bit`, then the UDM's remote syslog setting."
    }
    kubernetes = {
      name   = "Kubernetes container"
      query  = "kube_namespace:*"
      window = "30m"
      path   = "Datadog agent DaemonSet (k8s/prod/datadog). Check `kubectl -n datadog get pods` and `agent status` on one of them."
    }
    nas_files = {
      name   = "bigNASty log file"
      query  = "host:bigNASty filename:*"
      window = "1h"
      path   = "Datadog agent on bigNASty (nomad/datadog.hcl) tailing /var/log. Check `nomad job status datadog`."
    }
  }
}

resource "datadog_monitor" "logs_stopped" {
  for_each = local.logs_stopped

  name                = "${each.value.name} logs stopped arriving in Datadog"
  type                = "log alert"
  query               = "logs(\"${each.value.query}\").index(\"*\").rollup(\"count\").last(\"${each.value.window}\") < 1"
  message             = "No `${each.value.query}` logs for ${each.value.window}. ${each.value.path}\nLog-based monitors on this stream are blind until it's back.\n@slack-ops"
  include_tags        = true
  notify_no_data      = false
  renotify_interval   = 240
  require_full_window = false
  tags                = ["component:logging", "team:homelab"]

  monitor_thresholds {
    critical = "1"
  }
}
