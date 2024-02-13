resource "unifi_network" "default" {
  dhcp_start                 = "192.168.0.6"
  dhcp_stop                  = "192.168.0.254"
  dhcpd_boot_enabled         = false
  domain_name                = "localdomain"
  ipv6_ra_enable             = true
  multicast_dns              = false
  subnet                     = "192.168.0.0/24"
  vlan_id                    = 0
  dhcp_dns                   = local.nextdns_servers
  dhcp_enabled               = true
  dhcp_relay_enabled         = false
  dhcp_v6_dns                = []
  dhcp_v6_dns_auto           = true
  dhcp_v6_enabled            = false
  dhcp_v6_lease              = 86400
  dhcp_v6_start              = "::2"
  dhcp_v6_stop               = "::7d1"
  igmp_snooping              = false
  ipv6_pd_start              = "::2"
  ipv6_pd_stop               = "::7d1"
  ipv6_ra_preferred_lifetime = 14400
  ipv6_ra_valid_lifetime     = 0
  ipv6_ra_priority           = "high"
  name                       = "Default"
  purpose                    = "corporate"
  site                       = "default"
  wan_dns                    = []
}

resource "unifi_network" "default_wan1" {
  dhcp_dns                   = local.nextdns_servers
  dhcpd_boot_enabled         = false
  ipv6_ra_enable             = false
  multicast_dns              = false
  name                       = "Default (WAN1)"
  purpose                    = "wan"
  vlan_id                    = 0
  wan_dns                    = local.nextdns_servers
  network_group              = ""
  wan_networkgroup           = "WAN"
  wan_type                   = "dhcp"
  wan_type_v6                = "disabled"
  dhcp_v6_dns_auto           = false
  dhcp_v6_lease              = 0
  ipv6_ra_preferred_lifetime = 0
  ipv6_ra_valid_lifetime     = 0
  lifecycle {
    ignore_changes = [
      ipv6_interface_type,
    ]
  }
}

resource "unifi_network" "default_wan2" {
  dhcp_dns                   = local.nextdns_servers
  name                       = "Backup (WAN2)"
  purpose                    = "wan"
  vlan_id                    = 0
  wan_dns                    = local.nextdns_servers
  network_group              = ""
  wan_networkgroup           = "WAN2"
  wan_type                   = "dhcp"
  wan_type_v6                = "disabled"
  dhcp_v6_dns_auto           = false
  dhcp_v6_lease              = 0
  ipv6_ra_preferred_lifetime = 0
  ipv6_ra_valid_lifetime     = 0
  lifecycle {
    ignore_changes = [
      ipv6_interface_type,
    ]
  }
}
