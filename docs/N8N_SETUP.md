# Wiring the n8n side

## Packages

| What | Needed? | Notes |
|---|---|---|
| [`n8n-nodes-wol`](https://www.npmjs.com/package/n8n-nodes-wol) (community node) | **Yes** | MIT, no runtime dependencies, published with npm provenance. Sends the magic packet with Node's built-in `dgram`. |
| `NODE_FUNCTION_ALLOW_BUILTIN`, Code-node tweaks | No | The community node does the UDP, not a Code node. |
| `wakeonlan` / `etherwake` binaries | No | |
| `N8N_COMMUNITY_PACKAGES_ENABLED` | Default `true` | Must not be turned off. |

n8n Cloud cannot send a LAN broadcast. Use self-hosted n8n, or a self-hosted n8n as a relay.

### Install the node
- **UI** (instance owner): Settings -> Community Nodes -> Install -> `n8n-nodes-wol`.
- **Container / folder install:**
  ```bash
  cd ~/.n8n/nodes && npm install n8n-nodes-wol@0.1.1    # then restart n8n
  ```
  In Docker the folder is `/home/node/.n8n/nodes` (mount it as a volume).

## Network path (the part that usually goes wrong)

| Direction | What | Rule |
|---|---|---|
| Egress, n8n -> LAN | UDP/9 to the subnet's directed broadcast (e.g. `10.10.10.255`) | n8n must sit on that L2 segment |
| Egress, n8n -> target | TCP to the health URL's host:port | for the "is it up yet?" poll |
| Ingress, caller -> n8n | `POST /webhook/wake-on-demand` | LAN, or via tunnel/proxy for outside callers |
| Ingress, to the target | none | the powered-off NIC handles the packet in hardware |

**Docker bridge networks do not forward broadcasts.** Pick one:

```yaml
# docker-compose.yml: simplest
services:
  n8n:
    image: docker.io/n8nio/n8n:2.44.6
    network_mode: host            # n8n now listens on the host's :5678
    environment:
      - N8N_PORT=5678
      - WEBHOOK_URL=https://n8n.example.com/     # only if exposed outside the LAN
    volumes:
      - n8n_data:/home/node/.n8n
volumes:
  n8n_data:
```
Alternatives: a macvlan network on the right NIC, or run n8n on the host. If n8n lives in another VLAN/subnet, put a tiny always-on relay on the target's segment (a Pi running `wakeonlan`) and call it over SSH/HTTP from n8n.

Check from the n8n host: `ip route get 10.10.10.255` must show the NIC on the target's subnet.

## Import and configure
1. Import `n8n/wake-on-demand.workflow.json` (Workflows -> Import from file).
2. Open the **Config** node and set:

   | Field | Example | Meaning |
   |---|---|---|
   | `mac` | `4c:ed:fb:91:9d:33` | NIC with `Wake-on: g` |
   | `broadcastAddress` | `10.10.10.255` | directed broadcast of its subnet |
   | `wolPort` | `9` | 9 (or 7); the NIC ignores the port |
   | `healthUrl` | `http://10.10.10.100:8088/health` | returns 200 only when fully up |
   | `pollSeconds` | `10` | keep under 65 so n8n holds the run in memory |
   | `maxPolls` | `36` | 36 x 10 s = 6 min before a 504 |

   Prebuilt for billiron: `examples/billiron/wake-on-demand.workflow.json`.
3. **Secure the webhook**: Webhook node -> Authentication -> *Header Auth* -> new credential (name `X-Wake-Token`, a long random value). Without it, anyone who can reach the URL can power on your server.
4. Publish the workflow, then call it:

```bash
curl -sS -X POST -H 'X-Wake-Token: <token>' https://n8n.example.com/webhook/wake-on-demand
curl -sS -X POST -H 'X-Wake-Token: <token>' 'https://n8n.example.com/webhook/wake-on-demand?wait=false'   # fire and forget -> 202
```

| Response | Meaning |
|---|---|
| `200 {"status":"up","woke":false}` | was already up, nothing sent |
| `200 {"status":"up","woke":true}` | packet sent and the host passed the health check |
| `504 {"status":"timeout"}` | packet sent, host never became healthy within `maxPolls` |
| `202 {"status":"wake-sent"}` | `?wait=false` |

## Triggers
Replace or add to the Webhook node: Schedule (wake at 08:00), GitHub Trigger on `workflow_job` queued (wake the self-hosted runner), Telegram/Slack command, or an *Execute Workflow* call from another workflow, then continue your job after the host is up.

## Keeping it up during long jobs
The idle detector treats an established client connection, GPU load, a logged-in session, or a CI job as busy. For anything else: `ssh host sudo idle-poweroff keepawake 6` (whole hours), or drop `/etc/idle-poweroff/no-autooff`.
