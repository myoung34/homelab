# LAN name for Jellyfin, for devices not on Tailscale (the TV): traefik's
# MetalLB VIP (k8s/prod/metallb/pool.yaml), so https://media.marcyoung.us.
# Off-LAN, this resolves to a private address and goes nowhere; remote
# viewers use https://media.king-gila.ts.net instead.
resource "cloudflare_dns_record" "media" {
  zone_id = local.marcyoung_us_zone_id
  name    = "media.marcyoung.us"
  content = "192.168.1.50"
  type    = "A"
  ttl     = "3600"
}
