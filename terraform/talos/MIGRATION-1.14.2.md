# Talos 1.14.2 + Kubernetes 1.37.2 Migration
#
# This PR migrates the Talos cluster from v1.13.7 with Kubernetes 1.36.2
# to Talos 1.14.2 with Kubernetes 1.37.2.
#
# ## Major Changes
#
# 1. **Config Document Migration**: All v1alpha1 configuration fields have
#    been migrated to their multi-document equivalents:
#    - `.machine.kubelet` -> `KubeletConfig`
#    - `.machine.install` -> `UnattendedInstallConfig`
#    - `.machine.network` -> `HostnameConfig`, `ResolverConfig`, `StaticHostConfig`
#    - `.machine.sysctls` -> `SysctlConfig`
#    - `.machine.features.kubernetesTalosAPIAccess` -> `KubeTalosAPIAccessConfig`
#    - `.machine.time` -> still handled in v1alpha1
#    - `.machine.kernel` -> `KernelModuleConfig`
#    - `.machine.disks` -> `UserVolumeConfig`
#    - `.machine.nodeLabels` -> `KubeNodeConfig`
#    - `.cluster.apiServer` -> `KubeAPIServerConfig`, `KubeAdmissionControlConfig`, etc.
#    - `.cluster.controllerManager` -> `KubeControllerManagerConfig`
#    - `.cluster.scheduler` -> `KubeSchedulerConfig`
#    - `.cluster.proxy` -> `KubeProxyConfig`
#    - `.cluster.network` -> `KubeNetworkConfig`
#    - `.cluster.discovery` -> `DiscoveryServiceConfig`
#    - `.cluster.extraManifests` -> `KubeExternalManifestConfig`
#    - `.cluster.inlineManifests` -> `KubeInlineManifestConfig`
#
# 2. **Talos Version**: 1.13.7 -> 1.14.2
# 3. **Kubernetes Version**: 1.36.2 -> 1.37.2
#
# ## Breaking Changes
#
# With Talos 1.14+, workload isolation is enabled by default via
# `SecurityProfileConfig` with `workloadIsolation: true`. This runs CRI,
# kubelet, and pods in a dedicated PID/mount namespace (`sandboxd`).
#
# **Important**: The deprecated in-tree Kubernetes iSCSI volume plugin
# does not work with workload isolation enabled (the kubelet cannot reach
# the host `iscsid` across the sandbox). Use a CSI driver instead. See
# the in-tree volume plugin deprecation note in the Talos 1.14.0 release.
#
# ## Migration Steps
#
# 1. **Upgrade nodes first** (still on old config):
#    `talosctl upgrade --image <schematic>:v1.14.2` on every node.
#    This ensures nodes can accept the new config format before terraform apply.
#
# 2. **Upgrade Kubernetes**:
#    `talosctl upgrade-k8s --to v1.37.2`
#
# 3. **Apply this PR** (terraform apply):
#    Bumps `talos_version` to 1.14.2 and `kubernetes_version` to 1.37.2
#    in `locals.tf`, and updates all templates to multi-document format.
#
# ## Verification
#
# - `terraform/talos/validate.sh` passes (CI runs this)
# - Nodes report Talos v1.14.2: `talosctl get machinestatus`
# - Kubernetes 1.37.2: `kubectl get nodes -o wide`
#
# ## Files Changed
#
# - `locals.tf`: Bumped `talos_version` to v1.14.2, `kubernetes_version` to v1.37.2
# - `templates/*.yaml.tmpl`: Migrated to multi-document config
# - `UPGRADE-1.14.2.md`: New migration guide
# - `nvidia.yaml.tmpl` (renamed from `bare-metal.yaml.tmpl`)
#
# ## References
#
# - Talos 1.14.0 release: https://github.com/siderolabs/talos/releases/tag/v1.14.0
# - Talos 1.14.2 release: https://github.com/siderolabs/talos/releases/tag/v1.14.2
# - Configuration document map: https://docs.siderolabs.com/talos/v1.14/reference/configuration/document-map
# - Workload isolation: https://docs.siderolabs.com/talos/v1.14/getting-started/whats-new-in-talos#workload-isolation-sandboxd
