# For the Raspberry Pi 4 and Pi 5 overlays from pi.yaml.
# Regenerate via:
#   curl -X POST --data-binary @pi.yaml https://factory.talos.dev/schematics
# and drop the returned "id" in below.
  rpi_overlay_sha   = "8c0ab3c46bd174822da61ad52d4f014b05dc7e7d7dd8910bd2b57b0811086d1e" # pragma: allowlist secret
  rpi5_overlay_sha   = "0f774a083686a512e4f912ade768ab366351b3d457fdbcb188c6cf7223cc5791" # pragma: allowlist secret

  # Bare-metal amd64 + Radeon (amdgpu) schematic from bare.yaml. No overlay on
  # the Pi images. Regenerate via:
  #   curl -X POST --data-binary @bare.yaml https://factory.talos.dev/schematics
  # and drop the returned "id" in below.
  bare_metal_sha   = "c74594ca0d5f8b6fe7e6a73c1258da7dd48cf8278684f4d40b996a248635fb95" # pragma: allowlist secret

# Version pins.
  talos_version      = "v1.14.2"
  kubernetes_version = "v1.37.2"