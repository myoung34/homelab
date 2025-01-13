resource "cloudflare_record" "pergola-lights" {
  zone_id = local.marcyoung_us_zone_id
  name    = "pergola-lights.iot.marcyoung.us"
  content = "192.168.4.100"
  type    = "A"
  ttl     = "3600"
}

resource "cloudflare_record" "garage-switch" {
  zone_id = local.marcyoung_us_zone_id
  name    = "garage-switch.iot.marcyoung.us"
  content = "192.168.4.101"
  type    = "A"
  ttl     = "3600"
}

resource "cloudflare_record" "front-porch-switch" {
  zone_id = local.marcyoung_us_zone_id
  name    = "front-porch-switch.iot.marcyoung.us"
  content = "192.168.4.103"
  type    = "A"
  ttl     = "3600"
}

resource "cloudflare_record" "liam-room-starlights" {
  zone_id = local.marcyoung_us_zone_id
  name    = "liam-room-starlights.iot.marcyoung.us"
  content = "192.168.4.104"
  type    = "A"
  ttl     = "3600"
}

resource "cloudflare_record" "ecobee" {
  zone_id = local.marcyoung_us_zone_id
  name    = "ecobee.iot.marcyoung.us"
  content = "192.168.4.105"
  type    = "A"
  ttl     = "3600"
}

resource "cloudflare_record" "tubeszb-upstairs" {
  zone_id = local.marcyoung_us_zone_id
  name    = "tubeszb-upstairs.iot.marcyoung.us"
  content = "192.168.4.108"
  type    = "A"
  ttl     = "3600"
}

resource "cloudflare_record" "ble-proxy" {
  zone_id = local.marcyoung_us_zone_id
  name    = "ble-proxy.iot.marcyoung.us"
  content = "192.168.4.109"
  type    = "A"
  ttl     = "3600"
}

resource "cloudflare_record" "plaato-keg" {
  zone_id = local.marcyoung_us_zone_id
  name    = "plaato-keg.iot.marcyoung.us"
  content = "192.168.4.110"
  type    = "A"
  ttl     = "3600"
}

resource "cloudflare_record" "plaato-airlock" {
  zone_id = local.marcyoung_us_zone_id
  name    = "plaato-airlock.iot.marcyoung.us"
  content = "192.168.4.111"
  type    = "A"
  ttl     = "3600"
}

resource "cloudflare_record" "liamplug" {
  zone_id = local.marcyoung_us_zone_id
  name    = "liamplug.iot.marcyoung.us"
  content = "192.168.4.112"
  type    = "A"
  ttl     = "3600"
}

resource "cloudflare_record" "plug1" {
  zone_id = local.marcyoung_us_zone_id
  name    = "plug1.iot.marcyoung.us"
  content = "192.168.4.113"
  type    = "A"
  ttl     = "3600"
}

resource "cloudflare_record" "plug2" {
  zone_id = local.marcyoung_us_zone_id
  name    = "plug2.iot.marcyoung.us"
  content = "192.168.4.107"
  type    = "A"
  ttl     = "3600"
}

resource "cloudflare_record" "plug3" {
  zone_id = local.marcyoung_us_zone_id
  name    = "plug3.iot.marcyoung.us"
  content = "192.168.4.114"
  type    = "A"
  ttl     = "3600"
}

resource "cloudflare_record" "driveway-switch" {
  zone_id = local.marcyoung_us_zone_id
  name    = "driveway-switch.iot.marcyoung.us"
  content = "192.168.4.120"
  type    = "A"
  ttl     = "3600"
}

resource "cloudflare_record" "unicorn" {
  zone_id = local.marcyoung_us_zone_id
  name    = "unicorn.iot.marcyoung.us"
  content = "192.168.4.166"
  type    = "A"
  ttl     = "3600"
}

resource "cloudflare_record" "neon-lights" {
  zone_id = local.marcyoung_us_zone_id
  name    = "neon-lights.iot.marcyoung.us"
  content = "192.168.4.250"
  type    = "A"
  ttl     = "3600"
}

resource "cloudflare_record" "klipper" {
  zone_id = local.marcyoung_us_zone_id
  name    = "klipper.iot.marcyoung.us"
  content = "192.168.0.69"
  type    = "A"
  ttl     = "3600"
}

resource "cloudflare_record" "barcaderator" {
  zone_id = local.marcyoung_us_zone_id
  name    = "barcaderator.iot.marcyoung.us"
  content = "192.168.2.70"
  type    = "A"
  ttl     = "3600"
}

resource "cloudflare_record" "pinball" {
  zone_id = local.marcyoung_us_zone_id
  name    = "pinball.iot.marcyoung.us"
  content = "192.168.4.174"
  type    = "A"
  ttl     = "3600"
}
