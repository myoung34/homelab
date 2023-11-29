data "unifi_ap_group" "default" {
}

data "unifi_ap_group" "garage" {
  name = "Garage"
}

data "unifi_user_group" "default" {
}

resource "unifi_wlan" "bill_wi_the_science_fi" {
  name       = "Bill Wi The Science Fi"
  security   = "wpapsk"
  no2ghz_oui = false
  wlan_band  = "5g"

  network_id    = unifi_network.wifi.id
  ap_group_ids  = [data.unifi_ap_group.default.id]
  user_group_id = data.unifi_user_group.default.id

  lifecycle {
    ignore_changes = [
      passphrase
    ]
  }
}

resource "unifi_wlan" "fbi_van" {
  name       = "FBI Van"
  security   = "wpapsk"
  no2ghz_oui = false
  wlan_band  = "both"

  network_id    = unifi_network.your_mom.id
  ap_group_ids  = [data.unifi_ap_group.default.id]
  user_group_id = data.unifi_user_group.default.id

  lifecycle {
    ignore_changes = [
      passphrase
    ]
  }
}

resource "unifi_wlan" "it_burns_when_ip" {
  name       = "It Burns When IP"
  security   = "wpapsk"
  no2ghz_oui = false
  wlan_band  = "both"

  network_id    = unifi_network.iot.id
  ap_group_ids  = [data.unifi_ap_group.default.id]
  user_group_id = data.unifi_user_group.default.id

  lifecycle {
    ignore_changes = [
      passphrase
    ]
  }
}

resource "unifi_wlan" "the_lan_before_time" {
  name       = "The LAN Before Time"
  security   = "wpapsk"
  no2ghz_oui = false
  wlan_band  = "both"

  network_id    = unifi_network.wifi.id
  ap_group_ids  = [data.unifi_ap_group.garage.id]
  user_group_id = data.unifi_user_group.default.id

  lifecycle {
    ignore_changes = [
      passphrase
    ]
  }
}
