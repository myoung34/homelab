resource "cloudflare_dns_record" "hotchicken_rocks" {
  for_each = toset(local.fastly_a_records)
  zone_id  = local.hotchicken_rocks_zone_id
  name     = "hotchicken.rocks"
  content  = each.value
  type     = "A"
  ttl      = "3600"
}

resource "cloudflare_dns_record" "www_hotchicken_rocks" {
  for_each = toset(local.fastly_a_records)
  zone_id  = local.hotchicken_rocks_zone_id
  name     = "www.hotchicken.rocks"
  content  = each.value
  type     = "A"
  ttl      = "3600"
}

resource "cloudflare_dns_record" "hotchicken-rocks-acme" {
  zone_id = local.hotchicken_rocks_zone_id
  name    = "_acme-challenge.hotchicken.rocks"
  content = "za98t9267mvm1jvn25.fastly-validations.com"
  type    = "CNAME"
  ttl     = "3600"
}

resource "cloudflare_dns_record" "www_hotchicken-rocks-acme" {
  zone_id = local.hotchicken_rocks_zone_id
  name    = "_acme-challenge.www.hotchicken.rocks"
  content = "1b0gza9yc5g2kt3nry.fastly-validations.com"
  type    = "CNAME"
  ttl     = "3600"
}

resource "fastly_service_compute" "hotchicken_rocks" {
  name          = "hotchicken.rocks"
  comment       = "Managed by Terraform"
  activate      = true
  force_destroy = true

  domain {
    name = "hotchicken.rocks"
  }

  domain {
    name = "www.hotchicken.rocks"
  }

  #package {
  #  filename         = "package.tar.gz"
  #  source_code_hash = data.fastly_package_hash.example.hash
  #}
  lifecycle {
    ignore_changes = [
      package,
      active_version,
      cloned_version,
      activate,
      force_destroy,
    ]
  }
}
