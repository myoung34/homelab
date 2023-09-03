resource "unifi_device" "usw" {
  name = "usw"

  allow_adoption    = false
  forget_on_destroy = false

  port_override {
    name            = "cluster 1,1"
    number          = 7
    port_profile_id = unifi_port_profile.cluster.id
  }
  port_override {
    name            = "cluster 1,2"
    number          = 3
    port_profile_id = unifi_port_profile.cluster.id
  }
  port_override {
    name            = "cluster 1,3"
    number          = 13
    port_profile_id = unifi_port_profile.cluster.id
  }
  port_override {
    name            = "cluster 1,4"
    number          = 16
    port_profile_id = unifi_port_profile.cluster.id
  }
  port_override {
    name            = "cluster 2,1"
    number          = 6
    port_profile_id = unifi_port_profile.cluster.id
  }
  port_override {
    name            = "cluster 2,2"
    number          = 4
    port_profile_id = unifi_port_profile.cluster.id
  }
  port_override {
    name            = "cluster 2,3"
    number          = 14
    port_profile_id = unifi_port_profile.cluster.id
  }
  port_override {
    name            = "cluster 2,4"
    number          = 5
    port_profile_id = unifi_port_profile.cluster.id
  }
  port_override {
    name            = "garage ap"
    number          = 2
    port_profile_id = unifi_port_profile.all.id
  }
  port_override {
    name            = "udm"
    number          = 23
    port_profile_id = unifi_port_profile.all.id
  }
}
