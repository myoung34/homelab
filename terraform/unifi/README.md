Unifi
=====

Notes
=====

I cannot currently update client devices, so instead I'll capture them here on occasion.

```
# Easiest is to just go to chrome dev tools -> network -> copy as cURL for clients
$ curl 'https://192.168.2.1/proxy/network/v2/api/site/default/clients/active?includeTrafficUsage=true' \
 .....  >clients.json
$ ( echo $'|name|mac|network|ip|\n|----|----|----|----|'; cat clients.json | jq -r '.[] | select(.display_name!=null) | select(.use_fixedip==true) | "|" + .display_name + "|" + .mac + "|" + .network_name + "|" + .ip + "|"' ) | pbcopy
```

|name|mac|network|ip|
|----|----|----|----|
|barcaderator|f8:e4:e3:75:0e:3b|WIFI|192.168.2.70|
|bigNASty|00:11:32:97:da:3c|NAS|192.168.3.2|
|ble-proxy|64:e8:33:84:06:98|WIFI|192.168.4.109|
|cluster11|00:e0:4c:88:0b:85|cluster|192.168.1.19|
|cluster22|e4:5f:01:58:2d:7d|cluster|192.168.1.25|
|cluster23|e4:5f:01:58:de:82|cluster|192.168.1.26|
|cluster12|d8:3a:dd:28:50:51|cluster|192.168.1.21|
|cluster14|d8:3a:dd:55:cb:5e|cluster|192.168.1.23|
|cluster24|d8:3a:dd:55:c8:e0|cluster|192.168.1.27|
|cluster13|dc:a6:32:d3:86:35|cluster|192.168.1.22|
|cluster21|00:e0:4c:88:00:cd|cluster|192.168.1.24|
|neon-lights|40:22:d8:e3:f4:d8|WIFI|192.168.4.250|
|office brother|84:9e:56:d2:80:a0|printer|192.168.6.9|
|plaato-keg|84:0d:8e:e3:01:78|IoT|192.168.4.110|
|plaato-airlock|2c:f4:32:0f:78:68|IoT|192.168.4.111|
|plug1|e8:68:e7:f3:23:a8|IoT|192.168.4.113|
|plug2|a4:cf:12:b7:ff:5b|IoT|192.168.4.107|
|plug3|48:3f:da:2a:d7:01|IoT|192.168.4.114|
|tubeszb-upstairs|08:b6:1f:71:18:b7|IoT|192.168.4.108|
|tubeszb-workspace|ec:c9:ff:ba:61:1f|IoT|192.168.4.102|
