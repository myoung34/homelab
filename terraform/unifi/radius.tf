resource "unifi_radius_profile" "default" {
  name                    = "Default"
  interim_update_interval = 0
  use_usg_auth_server     = true
  auth_server {
    ip      = "192.168.0.1"
    port    = 1812
    xsecret = ""
  }


}
