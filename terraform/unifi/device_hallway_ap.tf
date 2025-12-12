resource "unifi_device" "hallway_ap" {
  name = "hallway ap"

  allow_adoption    = false
  forget_on_destroy = false
}
