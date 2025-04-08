resource "unifi_device" "udm_pro" {
  name = "Dream Machine Pro"

  allow_adoption    = false
  forget_on_destroy = false

  port_override {
    number = 1
  }

  port_override {
    name   = "office usw"
    number = 2
  }

  port_override {
    name    = "bignasty"
    number  = 4
    op_mode = "switch"
  }

  port_override {
    name   = "Port 5"
    number = 5
  }

  port_override {
    name   = "usw"
    number = 7
  }

  port_override {
    number = 8
  }

}
