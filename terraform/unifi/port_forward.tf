resource "unifi_port_forward" "http" {
  dst_port               = "80"
  fwd_ip                 = "192.168.1.21"
  fwd_port               = "80"
  name                   = "marcyoung.us"
  port_forward_interface = "wan"
  protocol               = "tcp"
}

resource "unifi_port_forward" "https" {
  dst_port               = "443"
  fwd_ip                 = "192.168.1.21"
  fwd_port               = "443"
  name                   = "marcyoung.us ssl"
  port_forward_interface = "wan"
  protocol               = "tcp"
}
