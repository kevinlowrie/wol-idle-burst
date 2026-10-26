# Prompt for the Claude session on the n8n host (desktop)

Paste everything inside the box into a Claude Code session that runs **on the machine that hosts n8n**
(or has shell access to it). Fill in the three `<<...>>` values first. This session needs no access to billiron.

For billiron the values are: MAC `4c:ed:fb:91:9d:33`, broadcast `10.10.10.255`, health URL `http://10.10.10.100:8088/health`.

````text
I run n8n and want an n8n workflow to wake a sleeping GPU server with Wake-on-LAN, wait until it is
healthy, and report back. The server side is already done. Your job is the n8n side: network path,
community node, workflow import, and an end-to-end check. Work step by step and show me what you find
before you change anything.

Target host
- WoL NIC MAC: <<MAC, e.g. 4c:ed:fb:91:9d:33>>
- Directed broadcast address of its subnet: <<e.g. 10.10.10.255>>
- Health URL that returns HTTP 200 once it has booted: <<e.g. http://10.10.10.100:8088/health>>

Facts you can rely on
- WoL is a UDP broadcast on layer 2. It cannot cross a router and does NOT cross a Docker bridge network.
  Packet: 6 x 0xFF then the MAC 16 times, UDP port 9, sent to the subnet's directed broadcast address.
- The server needs no inbound firewall rule for WoL (the NIC handles it while powered off).
- The workflow template is the file `n8n/wake-on-demand.workflow.json` in the repo
  https://github.com/<<owner>>/wol-idle-poweroff (or the copy I give you). It uses the community node
  `n8n-nodes-wol` (MIT, no dependencies) and has one "Config" node holding every host-specific value.
- Webhook contract: POST /webhook/wake-on-demand ->
  200 {"status":"up","woke":false}  already up, nothing sent
  200 {"status":"up","woke":true}   packet sent, host came up
  504 {"status":"timeout",...}      packet sent, host never became healthy
  202 {"status":"wake-sent",...}    when called with ?wait=false

Do this
1. DISCOVER. Report, without changing anything: how n8n is deployed (docker / compose / podman / systemd /
   npm / n8n Cloud), its version, its network mode, which host NIC and subnet it can reach, whether the
   subnet containing the target is directly attached to that NIC, and whether n8n Cloud is in use.
   If it is n8n Cloud, stop and tell me: Cloud cannot send LAN broadcasts and needs a LAN relay instead.
2. EGRESS (n8n -> LAN). Make sure the n8n process can send a UDP broadcast onto the target's L2 segment:
   - Docker/Podman bridge: switch n8n to host networking (`network_mode: host`, keep the n8n port
     reachable) or attach it with a macvlan on the right NIC. Show me the diff and ask before restarting n8n.
   - Host firewall: allow outbound UDP 9 to the broadcast address and outbound TCP to the health URL's
     host:port. Check nftables/iptables/ufw/firewalld; only add rules that are missing; show each one first.
   - Verify with `ip route get <broadcast>` and by sending a test packet (step 5).
3. INGRESS (caller -> n8n). Decide with me who triggers the wake and expose only what is needed:
   - LAN-only callers: the n8n webhook URL on the LAN is enough. Confirm WEBHOOK_URL / N8N_HOST are right.
   - Outside callers (GitHub webhook, phone, cloud service): propose one of Cloudflare Tunnel, Tailscale
     Funnel/Serve, or my existing reverse proxy. Expose ONLY `/webhook/wake-on-demand`, never the editor.
   - Whichever it is, enable Header Auth on the Webhook node (a Header Auth credential, long random
     value, header `X-Wake-Token`) so an unauthenticated request cannot power on the server.
4. INSTALL THE NODE. Install the community package `n8n-nodes-wol` (UI: Settings -> Community Nodes ->
   Install, or for containers `npm install n8n-nodes-wol` in the n8n user folder's `nodes/` directory,
   then restart). Confirm the "Wake-on-LAN" node appears. No other package or environment variable is needed.
5. IMPORT AND CONFIGURE. Import `n8n/wake-on-demand.workflow.json`. In its "Config" node set mac,
   broadcastAddress, wolPort (9), healthUrl, pollSeconds (10), maxPolls (36). Do NOT activate yet.
6. TEST SAFELY. First run `?wait=false` against the real MAC only if the server is currently OFF and I
   confirm. Otherwise test with a fake MAC (02:00:00:00:00:01) and a throwaway listener on UDP 40009
   (`nc -ul 40009` or a small python socket) so no real machine is woken. Show me the packet arrived and is
   102 bytes starting with six 0xFF. Then activate the workflow and call the production webhook with curl
   using the auth header. Report the HTTP status and body for: already up, wake+boot, timeout.
7. REPORT. Give me: what you changed (files, compose diffs, firewall rules), how to undo each change,
   the final webhook URL and header name (not the secret), and anything you could not verify.

Rules
- Never stop, restart or reconfigure containers or services other than n8n itself, and ask before restarting n8n.
- Do not expose the n8n editor or any port other than the webhook path to the internet.
- Do not print secrets. Do not wake the real server unless I say so in this conversation.
- If something is ambiguous (multiple NICs, VLANs, several n8n instances), ask me instead of guessing.
````
