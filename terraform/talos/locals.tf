# Version pins.

# N.B. `machine_image` and `machine_token` are required on controlplane.yaml.tmpl.
# `install_disk`, `image` are required on install-disk-and-hostname.yaml.tmpl.

locals {
  bare_metal_sha      = "c74594ca0d5f8b6fe7e6a73c1258da7dd48cf8278684f4d40b996a248635fb95"
  rpi_overlay_sha     = "8c0ab3c46bd174822da61ad52d4f014b05dc7e7d7dd8910bd2b57b0811086d1e"
  rpi5_overlay_sha    = "0f774a083686a512e4f912ade768ab366351b3d457fdbcb188c6cf7223cc5791"

  # Version pins.
  talos_version      = "v1.14.2"
  kubernetes_version = "v1.37.2"
}
