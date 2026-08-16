# klipper

Klipper + Moonraker, one Deployment per printer, pinned to whichever node has
that printer's MCU plugged in via USB. The UI lives in `k8s/prod/fluidd`.

## Printers

| name       | model   | board              | USB serial                 | status  |
|------------|---------|--------------------|----------------------------|---------|
| enderright | Ender 3 | SKR mini e3 v3     | `43002E000C50564837383420` | active  |
| enderleft  | Ender 3 | SKR mini e3 v3     | `4800420008504E5238363120` | active  |
| enderbig   | Ender 5 | SKR mini e3 v3     | `320014000350415339373620` | active  |

## Adding a printer

1. Flash Klipper, plug it in, get the serial from
   `ls /dev/serial/by-id/` (`usb-Klipper_<mcu>_<SERIAL>-if00`).
2. Uncomment/add its rule in `nodefeaturerule.yaml` with that serial.
3. Copy `enderright-configmap.yaml` and `enderright.yaml`, s/enderright/<name>/g,
   swap the by-id path (2 places in the Deployment) and the printer.cfg contents.
4. Add both files to `kustomization.yaml`.
5. Remove the generic `usb-02_1d50_614e.present` fallback affinity term from all
   printer Deployments — every Klipper MCU shares VID/PID `1d50:614e`, so with
   more than one printer only the per-serial labels pin correctly.
6. Add the instance in fluidd: `https://<name>` (tailnet).

## Node pinning

`nodefeaturerule.yaml` adds `feature.node.kubernetes.io/klipper-<name>=true` to
the node exposing that USB serial. NFD's usb `deviceClassWhitelist` already
includes class `02` (CDC), so no worker config change is needed. Don't add
`serial` to `deviceLabelFields` instead — that renames every existing `usb-*`
label and breaks the zooz/zwave affinities in ser2net.

Verify after sync:

```sh
kubectl get nodes -o json | jq '.items[].metadata.labels | with_entries(select(.key | test("klipper|1d50")))'
```

## Config lifecycle

`printer.cfg` / `moonraker.conf` are **seeds**: an init container copies them to
the PVC only if absent, because Klipper `SAVE_CONFIG` (bed mesh, PID, bltouch
z-offset) and fluidd's config editor must write to them. After first boot the
ConfigMaps are ignored; delete the file on the PVC (or the PVC) to re-seed.

enderright's seed came from
[enderleft.cfg](https://github.com/myoung34/dotfiles/blob/main/home/dot_config/enderleft.cfg)
including its SAVE_CONFIG calibration block as a starting point — run
`PID_CALIBRATE`, `PROBE_CALIBRATE`, and `BED_MESH_CALIBRATE` on the actual
printer.
