resource "unifi_device" "office_ap" {
  name = "office ap"

  allow_adoption    = false
  forget_on_destroy = false
}
