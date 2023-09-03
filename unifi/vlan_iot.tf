resource "unifi_network" "iot" {
  dhcp_dns = [
    "1.1.1.1",
    "8.8.8.8",
  ]

  purpose                    = "corporate"
  dhcp_start                 = "192.168.4.100"
  dhcp_stop                  = "192.168.4.254"
  dhcpd_boot_enabled         = false
  multicast_dns              = false
  name                       = "IoT"
  site                       = "default"
  subnet                     = "192.168.4.0/24"
  vlan_id                    = 4
  dhcp_enabled               = true
  dhcp_v6_dns_auto           = false
  dhcp_v6_lease              = 0
  ipv6_pd_start              = "::2"
  ipv6_pd_stop               = "::7d1"
  ipv6_ra_enable             = true
  ipv6_ra_preferred_lifetime = 0
  ipv6_ra_valid_lifetime     = 0

}

resource "unifi_port_profile" "iot" {
  name = "IoT"

  native_networkconf_id = unifi_network.iot.id
  dot1x_idle_timeout    = 0
  op_mode               = "switch"
  lifecycle {
    ignore_changes = [
      op_mode
    ]
  }
}
