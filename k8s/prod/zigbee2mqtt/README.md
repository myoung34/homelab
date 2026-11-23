devices
=======

The device list lives in each coordinator's `configuration.yaml`, under
`devices:` (IEEE address, `friendly_name`, location in `description`):

- `k8s/prod/zigbee2mqtt/configmap.yaml` (workspace/basement coordinator)
- `k8s/prod/zigbee2mqtt-upstairs/configmap.yaml` (upstairs coordinator)

Pair a new device, then add it there with a location-based `friendly_name`.
The init container copies the configmap over `/data/configuration.yaml` on
every pod start, so a device missing from it loses its name on restart.
