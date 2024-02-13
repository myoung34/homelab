resource "cloudflare_record" "github_blog" {
  for_each = toset(local.github_a_records)
  zone_id  = local.marcyoung_us_zone_id
  name     = "marcyoung.us"
  value    = each.value
  type     = "A"
  ttl      = "3600"
}

resource "cloudflare_record" "fallback_homelab" {
  zone_id = local.marcyoung_us_zone_id
  name    = "*"
  value   = local.home_ip
  type    = "A"
  ttl     = "3600"
}

resource "cloudflare_record" "consul_fallback" {
  for_each = toset(local.consul_nodes)
  zone_id = local.marcyoung_us_zone_id
  name    = "*.consul"
  value   = each.value
  type    = "A"
  ttl     = "3600"
}

resource "cloudflare_record" "kube_fallback" {
  for_each = toset(local.pihole_nodes)
  zone_id = local.marcyoung_us_zone_id
  name    = "*.kube"
  value   = each.value
  type    = "A"
  ttl     = "3600"
}
