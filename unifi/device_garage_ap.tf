resource "unifi_device" "garage_ap" {
  name = "garage ap"

  allow_adoption    = false
  forget_on_destroy = false
}
