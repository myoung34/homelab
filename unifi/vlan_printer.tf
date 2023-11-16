resource "unifi_network" "printer" {
  dhcp_dns = [
    "1.1.1.1",
    "8.8.8.8",
  ]
  dhcp_enabled               = true
  dhcp_relay_enabled         = false
  dhcp_start                 = "192.168.6.100"
  dhcp_stop                  = "192.168.6.254"
  dhcp_v6_dns                = []
  dhcp_v6_dns_auto           = true
  dhcp_v6_enabled            = false
  dhcp_v6_lease              = 86400
  dhcp_v6_start              = "::2"
  dhcp_v6_stop               = "::7d1"
  dhcpd_boot_enabled         = false
  igmp_snooping              = false
  ipv6_pd_start              = "::2"
  ipv6_pd_stop               = "::7d1"
  ipv6_ra_enable             = true
  ipv6_ra_preferred_lifetime = 14400
  ipv6_ra_valid_lifetime     = 0
  ipv6_ra_priority           = "high"
  multicast_dns              = false
  name                       = "printer"
  purpose                    = "corporate"
  site                       = "default"
  subnet                     = "192.168.6.0/24"
  vlan_id                    = 7
  wan_dns                    = []

}
