unifi FRR config example:

Unifi -> settings -> routing -> BGP
* Name: anything
* device: udm pro
* upload following config


```
router bgp 65000
 bgp router-id 192.168.1.1

 ! Define neighbors with remote AS
 neighbor 192.168.1.19 remote-as 65001
 neighbor 192.168.1.19 default-originate
 neighbor 192.168.1.21 remote-as 65001
 neighbor 192.168.1.21 default-originate
 neighbor 192.168.1.22 remote-as 65001
 neighbor 192.168.1.22 default-originate
 neighbor 192.168.1.23 remote-as 65001
 neighbor 192.168.1.23 default-originate
 neighbor 192.168.1.24 remote-as 65001
 neighbor 192.168.1.24 default-originate
 neighbor 192.168.1.25 remote-as 65001
 neighbor 192.168.1.25 default-originate
 neighbor 192.168.1.26 remote-as 65001
 neighbor 192.168.1.26 default-originate
 neighbor 192.168.1.27 remote-as 65001
 neighbor 192.168.1.27 default-originate

 ! BGP address family
 address-family ipv4 unicast
  redistribute connected
  redistribute kernel

  ! Apply soft-reconfiguration and route-map per neighbor
  neighbor 192.168.1.19 soft-reconfiguration inbound
  neighbor 192.168.1.19 route-map ALLOW-ALL in
  neighbor 192.168.1.21 soft-reconfiguration inbound
  neighbor 192.168.1.21 route-map ALLOW-ALL in
  neighbor 192.168.1.22 soft-reconfiguration inbound
  neighbor 192.168.1.22 route-map ALLOW-ALL in
  neighbor 192.168.1.23 soft-reconfiguration inbound
  neighbor 192.168.1.23 route-map ALLOW-ALL in
  neighbor 192.168.1.24 soft-reconfiguration inbound
  neighbor 192.168.1.24 route-map ALLOW-ALL in
  neighbor 192.168.1.25 soft-reconfiguration inbound
  neighbor 192.168.1.25 route-map ALLOW-ALL in
  neighbor 192.168.1.26 soft-reconfiguration inbound
  neighbor 192.168.1.26 route-map ALLOW-ALL in
  neighbor 192.168.1.27 soft-reconfiguration inbound
  neighbor 192.168.1.27 route-map ALLOW-ALL in
 exit-address-family

! Define route-map
route-map ALLOW-ALL permit 10
!

line vty
!
```

To debug:

From unifi UDM pro via SSH:

```
root@DreamMachinePro:~# systemctl status frr
...

root@DreamMachinePro:~# journalctl -xe --no-pager
..

root@DreamMachinePro:~# vtysh -c 'show ip bgp'
BGP table version is 10, local router ID is 192.168.1.1, vrf id 0
Default local pref 100, local AS 65000
Status codes:  s suppressed, d damped, h history, * valid, > best, = multipath,
               i internal, r RIB-failure, S Stale, R Removed
Nexthop codes: @NNN nexthop's vrf id, < announce-nh-self
Origin codes:  i - IGP, e - EGP, ? - incomplete
RPKI validation codes: V valid, I invalid, N Not found

   Network          Next Hop            Metric LocPrf Weight Path
*> 192.168.0.0/24   0.0.0.0                  0         32768 ?
*> 192.168.1.0/24   0.0.0.0                  0         32768 ?
*> 192.168.2.0/24   0.0.0.0                  0         32768 ?
*> 192.168.3.0/24   0.0.0.0                  0         32768 ?
*> 192.168.4.0/24   0.0.0.0                  0         32768 ?
*> 192.168.5.0/26   0.0.0.0                  0         32768 ?
*> 192.168.6.0/24   0.0.0.0                  0         32768 ?
*= 192.168.250.100/32
                    192.168.1.26                           0 65001 i
*=                  192.168.1.25                           0 65001 i
*=                  192.168.1.24                           0 65001 i
*=                  192.168.1.27                           0 65001 i
*=                  192.168.1.21                           0 65001 i
*=                  192.168.1.22                           0 65001 i
*=                  192.168.1.23                           0 65001 i
*>                  192.168.1.19                           0 65001 i
*> 209.30.118.0/23  0.0.0.0                  0         32768 ?

Displayed  9 routes and 16 total paths
```
