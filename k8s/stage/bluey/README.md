Bluey VM
========

First you have to get a custom ubuntu image

For me this is a local disk using `local-path-storage` CSI
The default images for ubuntu are 2Gi, which are too small.

A custom CDI controller will use this DataVolume to create a PVC with the same name and proper spec/annotations so that an import-specific controller detects it and launches an importer pod. This pod will gather the image specified in the source field.

Because I'm copying a qcow2 .img I need two volumes (PV/PVC)
* ubuntu-scratch (unpacking the image)
* ubuntu (the raw image post unpack)

```
$ k apply -f dv_ubuntu.yaml
```

You can watch the status of the copy:

```
$ kubectl logs -f importer-ubuntu # importer-{name of importer}
```

When that's done, I can simply delete it all

**NOTE** I use node local storage so deleting it retains the data. Make sure any set up does not clear the data.
You might need to do a targeted delete.


```
$ k delete -f dv_ubuntu.yaml
```

Next I can simply point a PV/PVC at the directory (because NLD) and use that as a boot image + cloud-init

```
$ kustomize build | kubectl apply -f -
```

Next use virtctl to jump in and look around:

```
$ virtctl console testvm
```


USB Passthrough
===============

You'll need to have a  privileged container with /dev mounted to /dev from the host,

Next you need to set spec.template.spec.domain.devices.clientPassthrough: {} on the VM

You'll need RBAC to use the virtualmachine commands, Im lazy and allowed * to * in namespace * . Dont do this.

For my USB info, it is in 1-6.1, so:

```
$ echo $(talosctl --talosconfig $(pwd)/talosconfig read /sys/bus/usb/devices/1-6.1/idVendor):$(talosctl --talosconfig $(pwd)/talosconfig read /sys/bus/usb/devices/1-6.1/idProduct)

0a12:0001
```

Lastly install virtctl and run `$ virtctl usbredir 0a12:0001 testvm` where the device id from talos:

See usbredir.yaml for how this works in reality. That `usbredir` must stay up for as long as USB passthrough is needed.

Now inside your VM you can utilize the usb as though its native.
