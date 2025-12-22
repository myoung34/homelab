resource "unifi_device" "living_room_u6_iw" {
  name = "media room u6-iw"

  allow_adoption    = false
  forget_on_destroy = false

  port_override {
    name   = "garage"
    number = 1
  }
  port_override {
    name   = "media room kodi"
    number = 3
  }
  port_override {
    name   = "ps5"
    number = 2
  }
}
