resource "unifi_network" "your_mom" {
  dhcp_dns = [
    "1.1.1.1",
    "8.8.8.8",
  ]
  dhcp_enabled               = true
  dhcp_relay_enabled         = false
  dhcp_start                 = "192.168.5.10"
  dhcp_stop                  = "192.168.5.14"
  dhcp_v6_dns                = []
  dhcp_v6_dns_auto           = false
  dhcp_v6_enabled            = false
  dhcp_v6_lease              = 0
  dhcpd_boot_enabled         = true
  dhcpd_boot_filename        = "netboot.xyz.kpxe"
  dhcpd_boot_server          = "192.168.3.2"
  igmp_snooping              = false
  ipv6_pd_start              = "::2"
  ipv6_pd_stop               = "::7d1"
  ipv6_ra_enable             = true
  ipv6_ra_preferred_lifetime = 0
  ipv6_ra_valid_lifetime     = 0
  multicast_dns              = true
  name                       = "yourmom"
  purpose                    = "corporate"
  site                       = "default"
  subnet                     = "192.168.5.0/28" # 192.168.5.0 -> 192.168.5.15
  # 192.168.5.0/28    192.168.5.0   -> 192.168.5.15
  # 192.168.5.16/28 	192.168.5.16  -> 192.168.5.31
  # 192.168.5.32/27   192.168.5.32  -> 192.168.5.63
  # 192.168.5.64/26   192.168.5.64  -> 192.168.5.127
  # 192.168.5.128/25  192.168.5.128 -> 192.168.5.255
  vlan_id = 6
  wan_dns = []
}
