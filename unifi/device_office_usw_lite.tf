resource "unifi_device" "office_usw_lite" {
  name = "office usw lite"

  allow_adoption    = false
  forget_on_destroy = false

  port_override {
    number          = 5
    port_profile_id = unifi_port_profile.lan.id
  }
  port_override {
    name            = "livingroom usw"
    number          = 1
    port_profile_id = unifi_port_profile.all.id
  }
  port_override {
    name            = "office ap"
    number          = 3
    port_profile_id = unifi_port_profile.all.id
  }
  port_override {
    name            = "printer"
    number          = 4
    port_profile_id = unifi_port_profile.printer.id
  }
  port_override {
    name            = "usw"
    number          = 2
    port_profile_id = unifi_port_profile.all.id
  }
}
