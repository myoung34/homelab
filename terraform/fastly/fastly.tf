resource "fastly_service_compute" "test-hotchicken" {
  name          = "evenly-uncommon-porpoise.edgecompute.app"
  comment       = "Managed by Terraform"
  activate      = true
  force_destroy = true

  domain {
    name = "evenly-uncommon-porpoise.edgecompute.app"
  }
  domain {
    name = "test.hotchicken.rocks"
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
