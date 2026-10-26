# wol-idle-poweroff

Run a power-hungry box (GPU inference, render, CI builder) **only when you need it**.
n8n wakes it with Wake-on-LAN, waits until it is actually healthy, and the box powers itself off again after it has been idle.

```
caller --POST--> n8n webhook --health?--> up? ──yes──> 200 woke:false
                                   │no
                                   └─ magic packet (n8n-nodes-wol, UDP broadcast) ─> NIC wakes the board
                                      poll health every 10 s ──up──> 200 woke:true   (or 504 after 6 min)

host: idle-poweroff.timer (every 2 min) ── idle for 30 min ──> systemctl poweroff
```

## What is in here
| Path | What |
|---|---|
| `bin/idle-poweroff` | idle detector + poweroff (`run`, `status`, `keepawake [hours]`) |
| `systemd/`, `etc/idle-poweroff.conf`, `install.sh`, `uninstall.sh` | timer/service and default config (ships in `DRY_RUN=1`) |
| `n8n/wake-on-demand.workflow.json` | importable workflow; one **Config** node holds your host's values |
| `tools/gen_workflow.py` | regenerate the workflow with your MAC/URL baked in |
| `docs/WOL_SETUP.md` | NIC, firmware, cold-start test |
| `docs/N8N_SETUP.md` | packages, network path, webhook security |
| `docs/DESKTOP_PROMPT.md` | prompt for a Claude session on the n8n host |
| `test/` | unit tests (shimmed) and a real-n8n end-to-end test |
| `examples/billiron/` | a worked example: 2x V100 inference box |

There is **no custom n8n node here on purpose**: [`n8n-nodes-wol`](https://www.npmjs.com/package/n8n-nodes-wol) already does the packet correctly (MIT, no dependencies, npm provenance). This repo adds the parts around it.

## Quick start
1. **Make the host wakeable** and prove it from a cold start: [docs/WOL_SETUP.md](docs/WOL_SETUP.md).
2. **Install the idle detector** on the host (stays in dry-run):
   ```bash
   ./install.sh                      # or ./install.sh examples/billiron/idle-poweroff.conf
   sudo idle-poweroff status         # shows why it is busy or idle
   journalctl -t idle-poweroff -f    # dry-run verdicts
   ```
   Edit `/etc/idle-poweroff/idle-poweroff.conf` (ports to watch, thresholds). When the cold-start test has passed, set `DRY_RUN=0`.
3. **Wire n8n**: [docs/N8N_SETUP.md](docs/N8N_SETUP.md). Install `n8n-nodes-wol`, import the workflow, set the Config node, secure the webhook.

## What counts as busy
Less than `BOOT_GRACE_MINUTES` since boot, GPU utilization above `GPU_UTIL_MAX`, an established client connection on any `WATCH_PORTS`, 5-minute load above `LOAD5_MAX`, a GitHub Actions job, apt/dpkg running, a running libvirt VM, a non-ignored podman container, a logged-in session (unless `IGNORE_SESSIONS=1`), `/etc/idle-poweroff/no-autooff`, or an active `keepawake`. Only continuous idleness for `IDLE_MINUTES` triggers poweroff.

## Tests
```bash
bash test/run-tests.sh      # 22 unit tests, no root, no hardware
bash test/e2e-n8n.sh        # needs podman + internet: real n8n, real n8n-nodes-wol, fake sleeping host
TEST_BROADCAST=<your-subnet-broadcast> bash test/e2e-n8n.sh   # same, over a real NIC
```
The end-to-end test checks four outcomes (already up / woke and booted / woke but never booted / `?wait=false`) and that the magic packet is byte-exact. It sends to a fake MAC (`02:00:00:00:00:01`), so it never wakes a real machine.

## Limits
- WoL works within one layer-2 segment. n8n must be on it (or use a relay there). n8n Cloud cannot do this.
- The firmware must allow wake from S5; check it with a real cold start. The OS and tests cannot prove it.
- Off means a normal boot time before the first request is served.

MIT licensed.
