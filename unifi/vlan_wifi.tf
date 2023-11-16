resource "unifi_network" "wifi" {
  dhcp_dns = [
    "1.1.1.1",
    "8.8.8.8",
  ]
  dhcp_enabled               = true
  dhcp_relay_enabled         = false
  dhcp_v6_dns                = []
  dhcp_v6_dns_auto           = true
  dhcp_v6_enabled            = false
  dhcp_v6_lease              = 86400
  dhcpd_boot_enabled         = true
  dhcpd_boot_filename        = "netboot.xyz.kpxe"
  dhcpd_boot_server          = "192.168.3.2"
  igmp_snooping              = false
  dhcp_v6_start              = "::2"
  dhcp_v6_stop               = "::7d1"
  ipv6_pd_start              = "::2"
  ipv6_pd_stop               = "::7d1"
  ipv6_ra_enable             = true
  ipv6_ra_preferred_lifetime = 14400
  ipv6_ra_valid_lifetime     = 0
  ipv6_ra_priority           = "high"
  multicast_dns              = true
  purpose                    = "corporate"
  site                       = "default"
  wan_dns                    = []
  dhcp_start                 = "192.168.2.6"
  dhcp_stop                  = "192.168.2.254"
  name                       = "WIFI"
  subnet                     = "192.168.2.0/24"
  vlan_id                    = 2
}
