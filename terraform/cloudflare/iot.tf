resource "cloudflare_dns_record" "tubeszb-upstairs" {
  zone_id = local.marcyoung_us_zone_id
  name    = "tubeszb-upstairs.iot.marcyoung.us"
  content = "192.168.4.108"
  type    = "A"
  ttl     = "3600"
}

resource "cloudflare_dns_record" "tubeszb-workspace" {
  zone_id = local.marcyoung_us_zone_id
  name    = "tubeszb-workspace.iot.marcyoung.us"
  content = "192.168.4.102"
  type    = "A"
  ttl     = "3600"
}

resource "cloudflare_dns_record" "ble-proxy-meater-1" {
  zone_id = local.marcyoung_us_zone_id
  name    = "ble-proxy-meater-1.iot.marcyoung.us"
  content = "192.168.4.109"
  type    = "A"
  ttl     = "3600"
}

resource "cloudflare_dns_record" "ble-proxy-meater-2" {
  zone_id = local.marcyoung_us_zone_id
  name    = "ble-proxy-meater-2.iot.marcyoung.us"
  content = "192.168.4.106"
  type    = "A"
  ttl     = "3600"
}

resource "cloudflare_dns_record" "plaato-keg" {
  zone_id = local.marcyoung_us_zone_id
  name    = "plaato-keg.iot.marcyoung.us"
  content = "192.168.4.110"
  type    = "A"
  ttl     = "3600"
}

resource "cloudflare_dns_record" "plaato-airlock" {
  zone_id = local.marcyoung_us_zone_id
  name    = "plaato-airlock.iot.marcyoung.us"
  content = "192.168.4.111"
  type    = "A"
  ttl     = "3600"
}

resource "cloudflare_dns_record" "plug1" {
  zone_id = local.marcyoung_us_zone_id
  name    = "plug1.iot.marcyoung.us"
  content = "192.168.4.113"
  type    = "A"
  ttl     = "3600"
}

resource "cloudflare_dns_record" "plug2" {
  zone_id = local.marcyoung_us_zone_id
  name    = "plug2.iot.marcyoung.us"
  content = "192.168.4.107"
  type    = "A"
  ttl     = "3600"
}

resource "cloudflare_dns_record" "plug3" {
  zone_id = local.marcyoung_us_zone_id
  name    = "plug3.iot.marcyoung.us"
  content = "192.168.4.112"
  type    = "A"
  ttl     = "3600"
}

resource "cloudflare_dns_record" "neon-lights" {
  zone_id = local.marcyoung_us_zone_id
  name    = "neon-lights.iot.marcyoung.us"
  content = "192.168.4.250"
  type    = "A"
  ttl     = "3600"
}

resource "cloudflare_dns_record" "klipper" {
  zone_id = local.marcyoung_us_zone_id
  name    = "klipper.iot.marcyoung.us"
  content = "192.168.0.69"
  type    = "A"
  ttl     = "3600"
}

resource "cloudflare_dns_record" "barcaderator" {
  zone_id = local.marcyoung_us_zone_id
  name    = "barcaderator.iot.marcyoung.us"
  content = "192.168.2.70"
  type    = "A"
  ttl     = "3600"
}

resource "cloudflare_dns_record" "pinball" {
  zone_id = local.marcyoung_us_zone_id
  name    = "pinball.iot.marcyoung.us"
  content = "192.168.4.174"
  type    = "A"
  ttl     = "3600"
}
