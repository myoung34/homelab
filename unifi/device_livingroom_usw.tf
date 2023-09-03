resource "unifi_device" "livingroom_usw" {
  name = "livingroom usw"

  allow_adoption    = false
  forget_on_destroy = false

  port_override {
    number          = 4
    port_profile_id = unifi_port_profile.disabled.id
  }
  port_override {
    number          = 5
    port_profile_id = unifi_port_profile.disabled.id
  }
  port_override {
    name            = "ps5"
    number          = 3
    port_profile_id = unifi_port_profile.lan.id
  }
  port_override {
    name            = "steampc"
    number          = 2
    port_profile_id = unifi_port_profile.lan.id
  }
  port_override {
    name            = "usw"
    number          = 1
    port_profile_id = unifi_port_profile.all.id
  }
}
