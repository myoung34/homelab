resource "unifi_device" "office_usw_lite" {
  name = "office usw lite"

  allow_adoption    = false
  forget_on_destroy = false

  port_override {
    name    = "tubeszb_upstairs"
    number  = 5
    op_mode = "switch"
  }
  port_override {
    name   = "livingroom usw"
    number = 1
  }
  port_override {
    name   = "office ap"
    number = 3
  }
  port_override {
    name   = "printer"
    number = 4
  }
  port_override {
    name   = "usw"
    number = 2
  }
}
