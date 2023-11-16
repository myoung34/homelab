resource "unifi_device" "livingroom_usw" {
  name = "livingroom usw"

  allow_adoption    = false
  forget_on_destroy = false

  port_override {
    number = 4
  }
  port_override {
    number = 5
  }
  port_override {
    name   = "ps5"
    number = 3
  }
  port_override {
    name   = "steampc"
    number = 2
  }
  port_override {
    name   = "usw"
    number = 1
  }
}
