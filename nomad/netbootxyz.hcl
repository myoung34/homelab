job "netbootxyz" {
  datacenters = ["dc1"]

  group "tftp" {
    network {
      mode = "host"
    }

    task "tftp" {
      template {
        data = <<EOH
#!ipxe
set os_arch amd64
set talos_hostname talos.hostname=cluster11
chain --autofree tftp://192.168.3.2/home-talos.ipxe
        EOH
        destination = "local/cluster11"
      }
      template {
        data = <<EOH
#!ipxe
set os_arch arm64
set talos_board talos.board=rpi_4
set talos_hostname talos.hostname=cluster12
chain --autofree tftp://192.168.3.2/home-talos.ipxe
        EOH
        destination = "local/cluster12"
      }
      template {
        data = <<EOH
#!ipxe
set os_arch arm64
set talos_board talos.board=rpi_4
set talos_hostname talos.hostname=cluster13
chain --autofree tftp://192.168.3.2/home-talos.ipxe
        EOH
        destination = "local/cluster13"
      }
      template {
        data = <<EOH
#!ipxe
set os_arch arm64
set talos_board talos.board=rpi_4
set talos_hostname talos.hostname=cluster14
chain --autofree tftp://192.168.3.2/home-talos.ipxe
        EOH
        destination = "local/cluster14"
      }
      template {
        data = <<EOH
#!ipxe
set os_arch amd64
set talos_hostname talos.hostname=cluster21
chain --autofree tftp://192.168.3.2/home-talos.ipxe
        EOH
        destination = "local/cluster21"
      }
      template {
        data = <<EOH
#!ipxe
set os_arch arm64
set talos_board talos.board=rpi_4
set talos_hostname talos.hostname=cluster22
chain --autofree tftp://192.168.3.2/home-talos.ipxe
        EOH
        destination = "local/cluster22"
      }
      template {
        data = <<EOH
#!ipxe
set os_arch arm64
set talos_board talos.board=rpi_4
set talos_hostname talos.hostname=cluster23
chain --autofree tftp://192.168.3.2/home-talos.ipxe
        EOH
        destination = "local/cluster23"
      }
      template {
        data = <<EOH
#!ipxe
set os_arch arm64
set talos_board talos.board=rpi_4
set talos_hostname talos.hostname=cluster24
chain --autofree tftp://192.168.3.2/home-talos.ipxe
        EOH
        destination = "local/cluster24"
      }
      template {
        data = <<EOH
#!ipxe

chain --autofree boot.cfg ||
ntp 0.pool.ntp.org ||
isset ${ip} || dhcp
chain --timeout 5000 https://boot.netboot.xyz/version.ipxe ||
sleep 5

set os Talos
isset ${talos_config_url} && set talos_config talos.config=${talos_config_url} ||
isset ${talos_platform} || set talos_platform metal
set boot_params page_poison=1 printk.devkmsg=on slab_nomerge slub_debug=P pti=on talos.platform=${talos_platform} ${talos_board} ${talos_hostname} ${talos_config} ${talos_hostname} initrd=initrd.magic ${cmdline}
imgfree

if ${os_arch} == amd64 (
    set talos_kernel https://pxe.factory.talos.dev/image/376567988ad370138ad8b2698212367b8edcb69b5fd68c80be1f2ec7d603b4ba/v1.8.3/kernel-amd64
    set talos_initrd https://pxe.factory.talos.dev/image/376567988ad370138ad8b2698212367b8edcb69b5fd68c80be1f2ec7d603b4ba/v1.8.3/initramfs-amd64.xz
) || if ${os_arch} == arm64 (
    set talos_kernel https://pxe.factory.talos.dev/image/893f789f3385fd07de4a4024e736036339ebd80e4ee83946b6cff3e26549b22b/v1.8.3/kernel-arm64
    set talos_initrd https://pxe.factory.talos.dev/image/893f789f3385fd07de4a4024e736036339ebd80e4ee83946b6cff3e26549b22b/v1.8.3/initramfs-arm64.xz
)

echo
echo Booting with the following kernel args:
echo ${boot_params}
echo
initrd ${talos_initrd}
kernel ${talos_kernel} ${boot_params}

boot
        EOH
        destination = "local/talos"
      }

      driver = "docker"

      env {
        TZ = "America/Chicago"
        PGID = "100"
        PUID = "1026"
        NGINX_PORT = "8080"
        WEB_APP_PORT = "3000"
      }

      config {
        force_pull = true
        image = "linuxserver/netbootxyz:latest"
        network_mode = "host"
        volumes = [
          "local/cluster11:/config/menus/MAC-00e04c880b85.ipxe",
          "local/cluster12:/config/menus/MAC-d83add285051.ipxe",
          "local/cluster13:/config/menus/MAC-dca632d38635.ipxe",
          "local/cluster14:/config/menus/MAC-d83add55cb5e.ipxe",
          "local/cluster21:/config/menus/MAC-00e04c8800cd.ipxe",
          "local/cluster22:/config/menus/MAC-e45f01582d7d.ipxe",
          "local/cluster23:/config/menus/MAC-e45f0158de82.ipxe",
          "local/cluster24:/config/menus/MAC-d83add55c8e0.ipxe",
          "local/talos:/config/menus/home-talos.ipxe",
        ]
        privileged = true
      }
      resources {

      }
    }
  }
}
