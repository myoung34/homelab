locals {
  talos_version = "1.8.1"

  # Schematic IDs
  # These are the schematic IDs for the Talos nodes. They are the same for all
  # nodes of a given type.
  #
  # To update a schematic ID:
  # 1. Update the schematic in the Talos dashboard
  # 2. Copy the new ID from the dashboard
  # 3. Update this file
  #
  # The IDs below are for the current production schematics.
  baremetal_schematic = "b8e8fbbe1b520989e6c52c8dc8303070cb42095997e76e812fa8892393e1d176" # pragma: allowlist secret
  pi_schematic        = "9992b4ade979cf2fc812e6f07e264d1f240d11b0d1eb795ce78771f8647a316" # pragma: allowlist secret

  # Network configuration
  # The cluster uses a /24 subnet. The IP addresses are statically assigned.
  #
  # The control-plane nodes use the first three IPs in the subnet.
  # The workers use the remaining IPs.
  network_cidr = "192.168.1.0/24"
  gateway_ip   = "192.168.1.1"
}
