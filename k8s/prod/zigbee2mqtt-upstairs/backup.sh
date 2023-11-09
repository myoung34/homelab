#!/bin/bash
filename=$(date '+%Y%m%d%H%M%S').tgz
for i in $(talosctl -n 192.168.1.26 list /var/mnt/storage/zigbee2mqtt | grep 192.168 | tail -n 4 | awk '{print $2}'); do talosctl -n 192.168.1.26 read /var/mnt/storage/zigbee2mqtt/$i >$i; done
tar czf ${filename} $(talosctl -n 192.168.1.26 list /var/mnt/storage/zigbee2mqtt | grep 192.168 | tail -n 4 | awk '{print $2}' | xargs echo)
rm $(talosctl -n 192.168.1.26 list /var/mnt/storage/zigbee2mqtt | grep 192.168 | tail -n 4 | awk '{print $2}' | xargs echo)
echo copy to https://minio.service.consul/browser/backups/emlnYmVlMm1xdHQv
