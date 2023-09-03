resource "unifi_setting_usg" "usg" {
  site = unifi_site.default.name
  dhcp_relay_servers = [
  ]
  firewall_guest_default_log = false
  firewall_lan_default_log   = false
  firewall_wan_default_log   = false
  multicast_dns_enabled      = false

}
