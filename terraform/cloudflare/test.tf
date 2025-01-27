resource "cloudflare_record" "fastly-test" {
  zone_id = local.hotchicken_rocks_zone_id
  name    = "test"
  content = "t.sni.global.fastly.net"
  type    = "CNAME"
  ttl     = "3600"
}

resource "cloudflare_record" "fastly-test-acme" {
  zone_id = local.hotchicken_rocks_zone_id
  name    = "_acme-challenge.test"
  content = "p14i5g98p3lpb1281p.fastly-validations.com"
  type    = "CNAME"
  ttl     = "3600"
}
