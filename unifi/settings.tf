resource "unifi_setting_mgmt" "default" {
  site         = unifi_site.default.name
  auto_upgrade = true
  ssh_enabled  = false
}
