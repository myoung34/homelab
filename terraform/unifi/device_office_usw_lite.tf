resource "unifi_device" "office_usw_lite" {
  name = "office usw lite"

  allow_adoption    = false
  forget_on_destroy = false

  port_override {
    name   = "marc-desktop"
    number = 5
  }

}
