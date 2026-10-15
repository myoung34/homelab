# Talos 1.14.2 + Kubernetes 1.37.2 migration
#
# Multi-document config documents
#
# Migrated from v1alpha1:
# - .machine.kubelet -> KubeletConfig
# - .machine.install -> UnattendedInstallConfig
# - .machine.network -> HostnameConfig, ResolverConfig, StaticHostConfig
# - .machine.sysctls -> SysctlConfig
# - .machine.features.kubernetesTalosAPIAccess -> KubeTalosAPIAccessConfig
# - .machine.time -> TimeSyncConfig (still in v1alpha1)
# - .machine.kernel -> KernelModuleConfig
# - .machine.disks -> UserVolumeConfig
# - .machine.nodeLabels -> KubeNodeConfig
# - .machine.nodeAnnotations -> KubeNodeConfig
# - .cluster.apiServer -> KubeAPIServerConfig, KubeAdmissionControlConfig, etc.
# - .cluster.controllerManager -> KubeControllerManagerConfig
# - .cluster.scheduler -> KubeSchedulerConfig
# - .cluster.proxy -> KubeProxyConfig
# - .cluster.network -> KubeNetworkConfig
# - .cluster.discovery -> DiscoveryServiceConfig
# - .cluster.extraManifests -> KubeExternalManifestConfig
# - .cluster.inlineManifests -> KubeInlineManifestConfig
---
