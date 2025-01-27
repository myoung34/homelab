resource "cloudflare_dns_record" "poopgeni_us" {
  for_each = toset(local.fastly_a_records)
  zone_id  = local.poopgeni_us_zone_id
  name     = "poopgeni.us"
  content  = each.value
  type     = "A"
  ttl      = "3600"
}

resource "cloudflare_dns_record" "www_poopgeni_us" {
  for_each = toset(local.fastly_a_records)
  zone_id  = local.poopgeni_us_zone_id
  name     = "www.poopgeni.us"
  content  = each.value
  type     = "A"
  ttl      = "3600"
}

resource "cloudflare_dns_record" "poopgeni-us-acme" {
  zone_id = local.poopgeni_us_zone_id
  name    = "_acme-challenge.poopgeni.us"
  content = "gkear51i7s4cs4er7h.fastly-validations.com"
  type    = "CNAME"
  ttl     = "3600"
}

resource "cloudflare_dns_record" "www_poopgeni-us-acme" {
  zone_id = local.poopgeni_us_zone_id
  name    = "_acme-challenge.www.poopgeni.us"
  content = "o53u8kjz9c0vps8tcl.fastly-validations.com"
  type    = "CNAME"
  ttl     = "3600"
}

resource "fastly_service_compute" "poopgeni_us" {
  name          = "poopgeni.us"
  comment       = "Managed by Terraform"
  activate      = true
  force_destroy = true

  domain {
    name = "poopgeni.us"
  }

  domain {
    name = "www.poopgeni.us"
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
