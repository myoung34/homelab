resource "unifi_device" "workspace_ap" {
  name = "workspace ap"

  allow_adoption    = false
  forget_on_destroy = false
}
