resource "datadog_logs_custom_pipeline" "k8s_stderr_level_remap" {
  is_enabled = true
  name       = "k8s stderr level remap"
  filter {
    query = "status:error kube_namespace:*"
  }
  processor {
    grok_parser {
      is_enabled = true
      name       = "klog / logrus level"
      samples    = ["I1126 15:19:28.123456       1 nfd-worker.go:538] \"starting feature discovery...\"", "E1126 19:51:23.895514       1 setting_controller.go:202] \"Unhandled Error\" err=\"x\"", "time=\"2026-11-26T15:19:28Z\" level=info msg=\"GetCapacity: rsp\" func=csi.logGRPC", "time=\"2026-11-26T15:19:28Z\" level=warning msg=\"Instance manager pod is deleted\""]
      source     = "message"
      grok {
        match_rules   = "klog_rule %%{regex(\"[IWEF]\"):klog_severity}%%{regex(\"\\\\d{4} \\\\d{2}:\\\\d{2}:\\\\d{2}\\\\.\\\\d+\")}%%{data}\nlogfmt_rule %%{regex(\"(.*\\\\s)?\")}level=%%{word:level}%%{data}"
        support_rules = ""
      }
    }
  }
  processor {
    category_processor {
      is_enabled = true
      name       = "klog severity to level"
      target     = "level"
      category {
        name = "info"
        filter {
          query = "@klog_severity:I"
        }
      }
      category {
        name = "warn"
        filter {
          query = "@klog_severity:W"
        }
      }
      category {
        name = "error"
        filter {
          query = "@klog_severity:E"
        }
      }
      category {
        name = "critical"
        filter {
          query = "@klog_severity:F"
        }
      }
    }
  }
  processor {
    status_remapper {
      is_enabled = true
      name       = "level to status"
      sources    = ["level"]
    }
  }
}
