resource "cloudflare_dns_record" "github_blog" {
  for_each = toset(local.github_a_records)
  zone_id  = local.markyoung_us_zone_id
  name     = "markyoung.us"
  content  = each.value
  type     = "A"
  ttl      = "3600"
}

resource "cloudflare_dns_record" "consul_fallback" {
  for_each = toset(local.consul_nodes)
  zone_id  = local.marcyoung_us_zone_id
  name     = "*.consul.marcyoung.us"
  content  = each.value
  type     = "A"
  ttl      = "3600"
}
