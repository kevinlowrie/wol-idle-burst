# Making the host wakeable

Do this before enabling `DRY_RUN=0`. If Wake-on-LAN does not work, an auto-poweroff leaves the machine off until someone presses the button.

## 1. OS: enable magic-packet wake on the NIC
Find the NIC and its MAC (use the one cabled to the segment n8n can reach): `ip -br link`, then `sudo ethtool <nic> | grep Wake-on`.
You want `Wake-on: g`.

Persistently, Ubuntu/netplan:

```yaml
# /etc/netplan/99-wol.yaml
network:
  version: 2
  ethernets:
    enp4s0:
      match:
        macaddress: 4c:ed:fb:91:9d:33
      wakeonlan: true
```
`sudo netplan apply`. Other options: a systemd `.link` file with `WakeOnLan=magic`, or NetworkManager `ethtool.wake-on-lan magic`.

If the NIC is a bridge port (`br-mgmt` over `enp4s0`), set it on the physical port, not the bridge.

## 2. Firmware
Enable the equivalent of *Power On By PCI-E/PCI* (ASUS server boards: Advanced -> APM Configuration) and disable *ErP/EuP Ready* (it cuts standby power to the NIC). Some boards also need *Wake on LAN* enabled explicitly. This cannot be checked from the OS.

## 3. Cold-start test (needs a fallback to power on by hand)
```bash
sudo systemctl poweroff                      # on the target
wakeonlan -i 10.10.10.255 4c:ed:fb:91:9d:33  # from any host on the same segment, after ~30 s
```
The NIC link LED should stay lit while powered off. If the host does not start, re-check the firmware options and that you used the MAC of the NIC that is cabled in.

## 4. Why full poweroff and not suspend
Check `cat /sys/power/mem_sleep`. If it only lists `[s2idle]` (common on servers), suspend saves almost no power and is a flaky wake target, especially with GPUs. Poweroff (S5) plus WoL is the reliable low-power state; the cost is a normal boot time.

## 5. Everything must start at boot
Anything you need after a wake (inference servers, runners, mounts) must be an enabled systemd unit. The n8n workflow only considers the host up when your `healthUrl` answers 200.
