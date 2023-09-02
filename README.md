## Homelab ##

Also see [this post](https://marcyoung.us/post/smart-home/)

### Layout

```
├── k8s
│   └── ArgoCD Application + ApplicationSet
├── misc
│   └── Random things. No real rule here
├── synology
│   └── Nomad jobs that run on the synology (some may be encrypted because chicken-and-egg (vault))
├── talos
│   └── Encrypted talos configs
└── unifi
│   └── todo
```

### Network Diagram

![](https://marcyoung.us/images/router.jpg)

Todo. In the meantime a tl;dr:

* Synology - Major backbone. Runs nomad natively (not k8s because no worky). Things that run here are stateful or data related
 * Datadog - o11y
 * Netboot.xyz - This is how I flash my talos easily. I build MAC's per node to a file. Some are ARM64, some are AMD64
 * `synology-ups-datadog` - custom script to send UPS metrics to datadog via Zapier, because of a [bug in go snmp](https://github.com/DataDog/integrations-core/issues/10899)
 * Vault - my way of handling secrets. Backed by Minio for cost/local reasons
 * traefik - How i expose services both from nomad but also kubernetes. Just a preference
 * minio - local s3 compatible system. I use it for backups (see `k8s/apps/prod/workflows`) and vault
* Kubernetes cluster
 * Runs on talos across a mixture of Raspberry Pi 4's and Rock Pi X (To get some AMD64 in there) on [pirack's](https://www.uctronics.com/uctronics-for-raspberry-pi-rack-with-micro-hdmi-adapter-boards-19-1u-rack-mount-supports-1-4-units-of-raspberry-pi-4-model-b-u6128.html) powered by PoE
 * Cluster naming is by rack and position. 1st rack, 1st position is `cluster11`. 2nd rack 3rd position would be `cluster23`
* Network Hardware
 * Main boi is a [unifi UDM pro](https://store.ui.com/us/en/products/udm-pro)
 * Fed from the UDM pro is a [24 port PoE unifi managed switch](https://store.ui.com/us/en/pro/category/all-switching/products/usw-pro-24-poe)
 * In the rooms as needed are [Unifi flex mini's](https://store.ui.com/us/en/pro/category/all-switching/products/usw-flex-mini)
 * For wireless I use [Unifi AP U6 Lites](https://store.ui.com/us/en/pro/category/all-wifi/products/u6-lite)
* Smart stuff
 * Most of this is covered [here - although not up to date](https://marcyoung.us/post/smart-home/)
 * I run ESPHome where I can: garage door, outside lights, keg scale, sonoff S31 plugs, kids room stuff. Everything is source controlled at `apps/prod/esphome/configmap.yaml`. Secrets and the configs are pulled and rendered via an init container.
 * Zigbee - [Conbee II](https://phoscon.de/en/conbee2) - For lights because I got a killer deal. Runs on k8s. Pinned to a specific node using [node feature discovery](https://github.com/kubernetes-sigs/node-feature-discovery) for [ser2net](https://github.com/cminyard/ser2net). That exposes it via TCP so that [zigbee2mqtt](https://www.zigbee2mqtt.io/) can schedule anywhere and talk over TCP via coredns. Backups are handled with an argocd workflow in `k8s/apps/prod/workflows/zigbee2mqtt.yaml` to minio.
 * Zwave - [Zooz 700](https://www.thesmartesthouse.com/products/zooz-usb-700-series-z-wave-plus-s2-stick-zst10-700) - Because Im masochistic but also had a zwave garage door sensor. Pinned to a specific node using [node feature discovery](https://github.com/kubernetes-sigs/node-feature-discovery) for [ser2net](https://github.com/cminyard/ser2net). That exposes it via TCP so that [zwave-js-ui](https://github.com/zwave-js/zwave-js-ui) can schedule anywhere and talk over TCP via coredns. Backups are handled with an argocd workflow in `k8s/apps/prod/workflows/zwavejsui.yaml` to minio.
 * [Hass](https://www.home-assistant.io/). This isnt crazy complex, I mostly have some daytime/sundown routines. Connects to zigbee2mqtt/zwave-js-ui over mqtt via [mosquitto](https://mosquitto.org/). Connects to esphome directly. Lights are exposed to google home for voice commands only. All of my configs are in source code at `k8s/apps/prod/hass/configmap.yaml`. Backups are handled natively with hass [folder watcher](https://www.home-assistant.io/integrations/folder_watcher/) with a trigger to put them in minio.


### Notes


#### To work with .age files

```
function phage() {
  mkdir -p $HOME/.age || :
  [[ ! -f $HOME/.age/recipient ]] && age-plugin-yubikey -l --serial 11087061 --slot 1 | grep -v '^#' >$HOME/.age/recipient
  [[ ! -f $HOME/.age/identity ]] && age-plugin-yubikey -i >$HOME/.age/identity
  filename=$(basename -- "$1")
  extension="${filename##*.}"

  if [[ ${extension} == "age" ]]; then
    filename="${filename%.*}"
    echo Decrypting ${filename}.age to ${filename}
    age -d -i ~/.age/identity -o ${filename} ${filename}.age
  else
    echo Encrypting ${filename} to ${filename}.age
    age -R "${HOME}/.age/recipient" -o ${filename}.age ${filename}
  fi
}

$ phage talosconfig.age #decrypt
$ phage talosconfig #encrypt
```
