resource "datadog_monitor" "pi_undervoltage" {
  draft_status           = "published"
  enable_logs_sample     = true
  evaluation_delay       = 0
  groupby_simple_monitor = false
  include_tags           = true
  message                = "{{@talos_node.name}} logged {{value}} `Undervoltage detected!` kernel lines in the last hour.\nThe Pi firmware caps the ARM clock while under-volted, so every container's CPU time balloons, probes time out (Longhorn engine-image, CSI) and ArgoCD health checks hit their deadline. Fix is hardware: PSU / USB-C cable / PoE HAT. Confirm with `talosctl -n {{@talos_node.name}} dmesg | grep -c Undervoltage`.\n@slack-ops"
  name                   = "Pi undervoltage on {{@talos_node.name}}"
  new_group_delay        = 0
  notify_audit           = false
  notify_no_data         = false
  query                  = "logs(\"service:talos @msg:*Undervoltage\\ detected*\").index(\"*\").rollup(\"count\").by(\"@talos_node\").last(\"1h\") > 10"
  renotify_interval      = 720
  renotify_occurrences   = 0
  require_full_window    = false
  tags                   = ["component:talos", "hw:pi", "team:homelab"]
  timeout_h              = 0
  type                   = "log alert"
  monitor_thresholds {
    critical = "10"
  }
}

resource "datadog_monitor" "all_nomad_jobs_have_died" {
  draft_status         = "published"
  evaluation_delay     = 0
  include_tags         = true
  message              = "All nomad jobs have died @slack-ops"
  name                 = "All nomad jobs have died"
  new_group_delay      = 0
  no_data_timeframe    = 10
  notify_audit         = false
  notify_no_data       = true
  query                = "sum(last_5m):avg:nomad.nomad.job_status.running{*} <= 0"
  renotify_interval    = 0
  renotify_occurrences = 0
  require_full_window  = false
  timeout_h            = 0
  type                 = "query alert"
  monitor_thresholds {
    critical = "0"
  }
}

resource "datadog_monitor" "pod_restart_looping" {
  draft_status     = "published"
  evaluation_delay = 0
  include_tags     = true
  message          = "{{kube_namespace.name}}/{{kube_container_name.name}} restarted {{value}} times in the last hour.\n`kubectl get pods -n {{kube_namespace.name}}`, then `kubectl describe pod` / `kubectl logs --previous` on the looping one.\n@slack-ops"
  name             = "{{kube_namespace.name}}/{{kube_container_name.name}} is restart-looping"
  new_group_delay  = 0
  notify_audit     = false
  notify_no_data   = false
  # By container, not pod_name: every CronJob run and replaced pod was its own
  # group (7.6k series a week), and a looping pod that got replaced left its
  # group stuck in Alert. sum, so a replaced pod's count dropping out reads as
  # a negative change, not a restart.
  query                = "change(max(last_1h),last_1h):sum:kubernetes.containers.restarts{*} by {kube_namespace,kube_container_name} > 5"
  renotify_interval    = 720
  renotify_occurrences = 0
  require_full_window  = false
  tags                 = ["component:kubernetes", "team:homelab"]
  timeout_h            = 1
  type                 = "query alert"
  monitor_thresholds {
    critical = "5"
    warning  = "2"
  }
}

resource "datadog_monitor" "cpu_saturated" {
  draft_status         = "published"
  evaluation_delay     = 0
  include_tags         = true
  message              = "{{host.name}} 5-min load per core averaged {{value}} over 30m.\nOn the 4-core Pis this means runnable tasks are queuing: exec probes (4s timeouts) start failing and pods crash-loop. Check `talosctl -n <node> read /proc/pressure/cpu`, `kubectl top pods -A --sort-by=cpu` for the node, and the undervoltage monitor.\n@slack-ops"
  name                 = "CPU saturated on {{host.name}}"
  new_group_delay      = 0
  notify_audit         = false
  notify_no_data       = false
  query                = "avg(last_30m):avg:system.load.norm.5{*} by {host} > 4"
  renotify_interval    = 720
  renotify_occurrences = 0
  require_full_window  = false
  tags                 = ["component:node", "team:homelab"]
  timeout_h            = 0
  type                 = "query alert"
  monitor_thresholds {
    critical          = "4"
    critical_recovery = "3"
    warning           = "2.5"
    warning_recovery  = "2"
  }
}

resource "datadog_monitor" "nas_space_low" {
  draft_status         = "published"
  evaluation_delay     = 0
  include_tags         = true
  message              = "NAS Space is approaching full  on {{host.name}} @sns-cloudwatch-alarm-topic-ops"
  name                 = "NAS Space is approaching full  on {{host.name}}"
  new_group_delay      = 0
  no_data_timeframe    = 10
  notify_audit         = false
  notify_no_data       = true
  query                = "avg(last_5m):avg:system.disk.free{host:bigNASty} < 1000000000000"
  renotify_interval    = 0
  renotify_occurrences = 0
  require_full_window  = true
  timeout_h            = 0
  type                 = "query alert"
  monitor_thresholds {
    critical          = "1e+12"
    critical_recovery = "1.5e+12"
    warning           = "2e+12"
    warning_recovery  = "3e+12"
  }
}

resource "datadog_monitor" "ups_is_discharging" {
  draft_status         = "published"
  evaluation_delay     = 0
  include_tags         = true
  message              = "@slack-ops\nSource: NAS agent SNMP check (loader: core) in nomad/datadog.hcl. No Data means that check broke."
  name                 = "UPS Is discharging"
  new_group_delay      = 0
  no_data_timeframe    = 10
  notify_audit         = false
  notify_no_data       = true
  query                = "avg(last_5m):avg:snmp.upsBatteryChargeValue{*} < 90"
  renotify_interval    = 0
  renotify_occurrences = 0
  require_full_window  = false
  timeout_h            = 0
  type                 = "query alert"
  monitor_thresholds {
    critical = "90"
  }
}

resource "datadog_monitor" "agent_not_reporting" {
  draft_status         = "published"
  evaluation_delay     = 0
  include_tags         = true
  message              = "{{host.name}} is not reporting to DD @slack-ops"
  name                 = "{{host.name}} is not reporting to DD"
  new_group_delay      = 300
  no_data_timeframe    = 30
  notify_audit         = false
  notify_no_data       = true
  query                = "\"datadog.agent.up\".over(\"*\").by(\"host\").last(2).count_by_status()"
  renotify_interval    = 0
  renotify_occurrences = 0
  require_full_window  = false
  timeout_h            = 0
  type                 = "service check"
  monitor_thresholds {
    critical = "1"
    ok       = "1"
    warning  = "1"
  }
}

resource "datadog_monitor" "talos_logs_stopped_arriving_in_datadog" {
  draft_status           = "published"
  enable_logs_sample     = false
  evaluation_delay       = 0
  groupby_simple_monitor = false
  include_tags           = true
  message                = "No service:talos logs for 30m. The Talos -> fluent-bit (Nomad on bigNASty, nomad/fluentbit.hcl) -> Datadog pipeline is down, so log-based monitors (e.g. Pi 5 NIC stalling) are blind. Check `nomad job status fluent-bit`.\n@slack-ops"
  name                   = "Talos logs stopped arriving in Datadog"
  new_group_delay        = 0
  notify_audit           = false
  notify_no_data         = false
  query                  = "logs(\"service:talos\").index(\"*\").rollup(\"count\").last(\"30m\") < 1"
  renotify_interval      = 240
  renotify_occurrences   = 0
  require_full_window    = false
  tags                   = ["component:logging", "component:talos", "team:homelab"]
  timeout_h              = 0
  type                   = "log alert"
  monitor_thresholds {
    critical = "1"
  }
}

resource "datadog_monitor" "a_unifi_os_update_has_occurred" {
  draft_status           = "published"
  enable_logs_sample     = false
  evaluation_delay       = 0
  groupby_simple_monitor = false
  include_tags           = false
  message                = "A Unifi OS update has occurred \n\n @slack-ops"
  name                   = "A Unifi OS update has occurred"
  new_group_delay        = 0
  notify_audit           = false
  on_missing_data        = "default"
  query                  = "logs(\"service:unifi \\\"https://fw-download.ubnt.com/\\\"\").index(\"*\").rollup(\"count\").last(\"5m\") > 0"
  renotify_interval      = 0
  renotify_occurrences   = 0
  require_full_window    = false
  timeout_h              = 0
  type                   = "log alert"
  monitor_thresholds {
    critical = "0"
  }
}

resource "datadog_monitor" "error_log_spike" {
  draft_status         = "published"
  evaluation_delay     = 0
  include_tags         = false
  message              = "Watchdog found an error-log pattern anomaly on {{log_source}} ({{service}}).\n@slack-ops"
  name                 = "A spike in error logs was detected on {{log_source}}"
  new_group_delay      = 0
  notify_audit         = false
  on_missing_data      = "default"
  query                = "events(\"source:watchdog tags:\\\"story_category:logs\\\" tags:\\\"story_type:logs_pattern_anomaly\\\"\").rollup(\"count\").by(\"story_key,env,service,log_source\").last(\"30m\") > 0"
  renotify_interval    = 0
  renotify_occurrences = 0
  require_full_window  = false
  timeout_h            = 0
  type                 = "event-v2 alert"
  monitor_thresholds {
    critical = "0"
  }
}

resource "datadog_monitor" "pi_5_nic_stalling" {
  draft_status           = "published"
  enable_logs_sample     = true
  evaluation_delay       = 0
  groupby_simple_monitor = false
  include_tags           = true
  message                = "{{@talos_node.name}} logged macb TX stall / NIC error lines in 15m ({{value}}; each kernel line arrives twice, via the kernel and service log streams).\nThe homelab#2455 mitigation (no TSO/GSO/SG on the macb NIC, BQL limit_min 65536) may be missing or not enough. Check `talosctl -n {{@talos_node.name}} get ethernetstatus` and terraform/talos/templates/pi5-nic.yaml.tmpl. Longhorn rebuild loops and the homelab/io-pressure taint usually follow.\n@slack-ops"
  name                   = "Pi 5 NIC stalling"
  new_group_delay        = 0
  notify_audit           = false
  notify_no_data         = false
  query                  = "logs(\"service:talos (@msg:*TX\\ stall\\ detected* OR @msg:*NETDEV\\ WATCHDOG* OR @msg:*end0\\:\\ Link\\ is\\ Down*)\").index(\"*\").rollup(\"count\").by(\"@talos_node\").last(\"15m\") > 0"
  renotify_interval      = 120
  renotify_occurrences   = 0
  require_full_window    = false
  tags                   = ["component:talos", "hw:pi5", "team:homelab"]
  timeout_h              = 0
  type                   = "log alert"
  monitor_thresholds {
    critical = "0"
  }
}

resource "datadog_monitor" "ups_is_on_battery" {
  draft_status         = "published"
  evaluation_delay     = 0
  include_tags         = true
  message              = "bigNASty's UPS reports status {{ups_status.name}} (OL = on line; OB = on battery, LB = low battery). Runtime left: {{value}}s.\nSource: NAS agent SNMP check (loader: core) in nomad/datadog.hcl. Companion to the charge monitor 62515638, which only fires once charge drops below 90.\n@slack-ops"
  name                 = "UPS is on battery ({{ups_status.name}})"
  new_group_delay      = 0
  notify_audit         = false
  notify_no_data       = false
  query                = "max(last_5m):max:snmp.upsBatteryRuntimeValue{!ups_status:ol*} by {ups_status} >= 0"
  renotify_interval    = 30
  renotify_occurrences = 0
  require_full_window  = false
  tags                 = ["component:ups", "team:homelab"]
  # The {!ups_status:ol*} series stops once power is back instead of
  # reporting 0, so without this the group never recovers.
  timeout_h = 1
  type      = "query alert"
  monitor_thresholds {
    critical = "0"
  }
}

resource "datadog_monitor" "a_unifi_device_update_has_occurred" {
  draft_status           = "published"
  enable_logs_sample     = true
  evaluation_delay       = 0
  groupby_simple_monitor = false
  include_tags           = false
  message                = "A unifi device update has occurred\n\n @slack-ops"
  name                   = "A unifi device update has occurred"
  new_group_delay        = 0
  notify_audit           = false
  on_missing_data        = "default"
  query                  = "logs(\"service:unifi ubnt-dpi-util \\\"version changed\\\"\").index(\"*\").rollup(\"count\").last(\"5m\") > 0"
  renotify_interval      = 0
  renotify_occurrences   = 0
  require_full_window    = false
  timeout_h              = 0
  type                   = "log alert"
  monitor_thresholds {
    critical = "0"
  }
}

resource "datadog_monitor" "argocd_app_unhealthy" {
  draft_status         = "published"
  evaluation_delay     = 0
  include_tags         = true
  message              = "ArgoCD app {{name.name}} has been {{health_status.name}} for 30m.\n`kubectl get application -n argocd {{name.name}} -o jsonpath='{.status.health}{.status.conditions}'`. Unknown with `context deadline exceeded` on a CRD means the application-controller is CPU-starved (see the CPU saturated / undervoltage monitors).\nmax across hosts on purpose: the argocd check runs on every node agent, so sum would count each app ~10x.\n@slack-ops"
  name                 = "ArgoCD app {{name.name}} is {{health_status.name}}"
  new_group_delay      = 0
  notify_audit         = false
  notify_no_data       = false
  query                = "min(last_30m):max:argocd.app_controller.app.info{!health_status:healthy} by {name,health_status} >= 1"
  renotify_interval    = 720
  renotify_occurrences = 0
  require_full_window  = true
  tags                 = ["component:argocd", "team:homelab"]
  timeout_h            = 1
  type                 = "query alert"
  monitor_thresholds {
    critical = "1"
  }
}

resource "datadog_monitor" "a_security_signal_has_been_generated" {
  draft_status         = "published"
  evaluation_delay     = 0
  include_tags         = true
  message              = "@slack-ops"
  name                 = "A security signal has been generated"
  new_group_delay      = 0
  notify_audit         = false
  notify_no_data       = false
  query                = "events(\"type:log_detection source:cloudtrail\").rollup(\"count\").last(\"5m\") > 0"
  renotify_interval    = 0
  renotify_occurrences = 0
  require_full_window  = false
  timeout_h            = 0
  type                 = "event-v2 alert"
  monitor_thresholds {
    critical = "0"
  }
}

resource "datadog_monitor" "nas_container_stopped" {
  draft_status         = "published"
  evaluation_delay     = 0
  include_tags         = false
  message              = "{{#is_alert}}A container has become stopped on {{host.name}} {{/is_alert}} \n{{#is_alert_recovery}}The container is no longer sotpped on {{host.name}} {{/is_alert_recovery}}  @slack-ops"
  name                 = "A container has become stopped on {{ host.name }}"
  new_group_delay      = 0
  notify_audit         = false
  on_missing_data      = "default"
  query                = "avg(last_1d):avg:docker.containers.stopped.total{host:bigNASty} > 1.5"
  renotify_interval    = 0
  renotify_occurrences = 0
  require_full_window  = false
  timeout_h            = 0
  type                 = "query alert"
  monitor_thresholds {
    critical = "1.5"
  }
}

resource "datadog_monitor" "disk_full" {
  draft_status         = "published"
  evaluation_delay     = 0
  include_tags         = true
  message              = "{{device.name}} on {{host.name}} is {{value}} used (fraction).\nPer-device, so small root/system partitions (e.g. bigNASty /dev/md0, a Pi's /dev/sda6) and Longhorn PVCs (/dev/longhorn/*) aren't hidden behind the NAS volume. NFS mounts and overlay are excluded as duplicates of the NAS volume and the node disk.\nReplaces monitors 11151579 and 11154436.\n@slack-ops"
  name                 = "Disk {{device.name}} is {{value}} full on {{host.name}}"
  new_group_delay      = 0
  notify_audit         = false
  notify_no_data       = false
  query                = "max(last_10m):max:system.disk.in_use{!device:overlay,!device:tmpfs,!device:shm,!device:/os-release,!device:/docker.sock*,!device:192.168.3.2*} by {host,device} > 0.95"
  renotify_interval    = 1440
  renotify_occurrences = 0
  require_full_window  = false
  tags                 = ["component:disk", "team:homelab"]
  timeout_h            = 0
  type                 = "query alert"
  monitor_thresholds {
    critical          = "0.95"
    critical_recovery = "0.92"
    warning           = "0.9"
    warning_recovery  = "0.85"
  }
}

resource "datadog_monitor" "synology_login_event" {
  draft_status           = "published"
  enable_logs_sample     = false
  evaluation_delay       = 0
  groupby_simple_monitor = false
  include_tags           = false
  message                = "A login event has occured\n\n @slack-ops"
  name                   = "Synology Login Event"
  new_group_delay        = 0
  notify_audit           = false
  on_missing_data        = "default"
  query                  = "logs(\"service:synology \\\"signed in to [DSM] successfully\\\"\").index(\"*\").rollup(\"count\").last(\"5m\") > 0"
  renotify_interval      = 0
  renotify_occurrences   = 0
  require_full_window    = false
  timeout_h              = 0
  type                   = "log alert"
  monitor_thresholds {
    critical = "0"
  }
}
