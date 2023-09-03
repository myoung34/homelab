resource "unifi_network" "simplisafe" {
  dhcp_dns = [
    "1.1.1.1",
    "8.8.8.8",
  ]
  dhcp_enabled               = true
  dhcp_relay_enabled         = false
  dhcp_start                 = "192.168.5.6"
  dhcp_stop                  = "192.168.5.254"
  dhcp_v6_dns                = []
  dhcp_v6_dns_auto           = false
  dhcp_v6_enabled            = false
  dhcp_v6_lease              = 0
  dhcpd_boot_enabled         = false
  igmp_snooping              = false
  ipv6_pd_start              = "::2"
  ipv6_pd_stop               = "::7d1"
  ipv6_ra_enable             = true
  ipv6_ra_preferred_lifetime = 0
  ipv6_ra_valid_lifetime     = 0
  multicast_dns              = false
  name                       = "Simplisafe"
  purpose                    = "guest"
  site                       = "default"
  subnet                     = "192.168.5.0/24"
  vlan_id                    = 6
  wan_dns                    = []
}

resource "unifi_port_profile" "simplisafe" {
  name = "Simplisafe"

  isolation             = true
  native_networkconf_id = unifi_network.simplisafe.id
  dot1x_idle_timeout    = 0
  op_mode               = "switch"
  lifecycle {
    ignore_changes = [
      op_mode
    ]
  }
}
