resource "unifi_device" "living_room_uap" {
  name = "UAP-AC-IW"

  allow_adoption    = false
  forget_on_destroy = false
  port_override {
    name                = "PoE Out + Data"
    number              = 1
    op_mode             = "switch"
  }
}
