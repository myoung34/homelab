# Zone-based firewall (Network 11 forced the migration on 2026-11-11 and left
# every network in Internal, so all VLANs could reach each other and the
# gateway's management ports).
#
# Untrusted holds devices we don't control: IoT, the printer and the cameras
# (yourmom). Internal keeps Default, WIFI, NAS and cluster.

# Looked up through unifizbf so policies carry the controller's UUIDs, not the
# legacy ObjectIds paultyng keeps in state.
data "unifi_network" "zbf" {
  for_each = toset(["IoT", "printer", "yourmom"])
  provider = unifizbf
  name     = each.key
}

data "unifi_firewall_zone" "internal" {
  provider = unifizbf
  name     = "Internal"
}

data "unifi_firewall_zone" "external" {
  provider = unifizbf
  name     = "External"
}

data "unifi_firewall_zone" "gateway" {
  provider = unifizbf
  name     = "Gateway"
}

resource "unifi_firewall_zone" "untrusted" {
  provider = unifizbf
  name     = "Untrusted"
  network_ids = [
    # Controller's order; any other order is a perpetual diff.
    data.unifi_network.zbf["printer"].id,
    data.unifi_network.zbf["yourmom"].id,
    data.unifi_network.zbf["IoT"].id,
  ]
}

# A new zone defaults to Block All in both directions with Internal. Untrusted
# -> Internal stays blocked; Internal may reach Untrusted (Home Assistant on
# cluster driving ESPHome/Zigbee devices, printing) and replies come back via
# the auto-created respond policy.
resource "unifi_firewall_policy" "allow_internal_to_untrusted" {
  provider             = unifizbf
  name                 = "Allow Internal to Untrusted"
  action               = "ALLOW"
  protocol             = "all"
  ip_version           = "BOTH"
  create_allow_respond = true
  source = {
    zone_id         = data.unifi_firewall_zone.internal.id
    matching_target = "ANY"
  }
  destination = {
    zone_id         = unifi_firewall_zone.untrusted.id
    matching_target = "ANY"
  }
}

# Cameras (yourmom) are left out: Protect runs on the UDM.
resource "unifi_firewall_policy" "block_untrusted_gateway_mgmt" {
  provider   = unifizbf
  name       = "Block IoT and printer to gateway management"
  action     = "BLOCK"
  protocol   = "tcp"
  ip_version = "BOTH"
  source = {
    zone_id         = unifi_firewall_zone.untrusted.id
    matching_target = "NETWORK"
    network_ids     = [data.unifi_network.zbf["IoT"].id, data.unifi_network.zbf["printer"].id]
  }
  destination = {
    zone_id            = data.unifi_firewall_zone.gateway.id
    matching_target    = "ANY"
    port_matching_type = "SPECIFIC"
    port               = "22,80,443"
  }
}

# DHCP hands out NextDNS; stop IoT devices from bypassing it with hardcoded
# resolvers. People networks (Default, WIFI) are left alone: a hard block
# breaks phones/laptops with their own DNS settings.
resource "unifi_firewall_policy" "block_untrusted_dns_bypass" {
  provider   = unifizbf
  name       = "Block DNS except NextDNS (IoT)"
  action     = "BLOCK"
  protocol   = "tcp_udp"
  ip_version = "IPV4"
  source = {
    zone_id         = unifi_firewall_zone.untrusted.id
    matching_target = "NETWORK"
    network_ids     = [data.unifi_network.zbf["IoT"].id]
  }
  destination = {
    zone_id            = data.unifi_firewall_zone.external.id
    matching_target    = "IP"
    ips                = local.nextdns_servers
    match_opposite_ips = true
    port_matching_type = "SPECIFIC"
    port               = "53,853"
  }
}
