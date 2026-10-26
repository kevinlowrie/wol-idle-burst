#!/usr/bin/env python3
"""Generate the n8n "wake on demand" workflow JSON.

The committed n8n/wake-on-demand.workflow.json is the output of this script with placeholder values.
Use the flags to bake your own host in, or just edit the "Config" node after importing.
"""
import argparse
import json
import sys

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--mac", default="00:11:22:33:44:55", help="MAC of the NIC with Wake-on: g")
p.add_argument("--broadcast", default="192.168.1.255", help="directed broadcast address of the NIC's subnet")
p.add_argument("--wol-port", type=int, default=9)
p.add_argument("--health-url", default="http://192.168.1.50:8000/health", help="URL that returns 200 once the host is fully up")
p.add_argument("--poll-seconds", type=int, default=10, help="seconds between health checks (keep < 65 so n8n holds the run in memory)")
p.add_argument("--max-polls", type=int, default=36, help="health checks before giving up (36 x 10 s = 6 min)")
p.add_argument("--webhook-path", default="wake-on-demand")
p.add_argument("-o", "--output", default="-")
a = p.parse_args()


def cfg(name):
    return "={{ $('Config').first().json.%s }}" % name


def http(name, pos):
    return {
        "parameters": {
            "url": cfg("healthUrl"),
            "options": {"timeout": 3000, "response": {"response": {"fullResponse": True, "neverError": True}}},
        },
        "name": name, "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2, "position": pos,
        "onError": "continueRegularOutput",
    }


def cond(node_id, left, op, right, kind="number"):
    return {
        "parameters": {"conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose"},
            "conditions": [{"id": node_id, "leftValue": left, "rightValue": right,
                            "operator": {"type": kind, "operation": op}}],
            "combinator": "and"}, "options": {}},
    }


def if_node(name, pos, node_id, left, op, right, kind="number"):
    n = cond(node_id, left, op, right, kind)
    n.update({"name": name, "type": "n8n-nodes-base.if", "typeVersion": 2.2, "position": pos})
    return n


def respond(name, pos, code, status, extra):
    body = '={{ JSON.stringify({ status: "%s", %s }) }}' % (status, extra)
    return {"parameters": {"respondWith": "json", "responseBody": body, "options": {"responseCode": code}},
            "name": name, "type": "n8n-nodes-base.respondToWebhook", "typeVersion": 1.1, "position": pos}


def assign(name, value, kind):
    return {"id": "cfg-" + name, "name": name, "value": value, "type": kind}


nodes = [
    {"parameters": {"httpMethod": "POST", "path": a.webhook_path, "responseMode": "responseNode", "options": {}},
     "name": "Wake request", "type": "n8n-nodes-base.webhook", "typeVersion": 2, "position": [0, 240],
     "webhookId": "wol-wake-on-demand"},
    {"parameters": {"assignments": {"assignments": [
        assign("mac", a.mac, "string"),
        assign("broadcastAddress", a.broadcast, "string"),
        assign("wolPort", a.wol_port, "number"),
        assign("healthUrl", a.health_url, "string"),
        assign("pollSeconds", a.poll_seconds, "number"),
        assign("maxPolls", a.max_polls, "number")]}, "options": {}},
     "name": "Config", "type": "n8n-nodes-base.set", "typeVersion": 3.4, "position": [200, 240]},
    http("Already up?", [400, 240]),
    if_node("Up already", [600, 240], "up-already", "={{ $json.statusCode }}", "equals", 200),
    respond("Respond already up", [820, 120], 200, "up", "woke: false"),
    {"parameters": {"macAddress": cfg("mac"), "broadcastAddress": cfg("broadcastAddress"),
                    "port": cfg("wolPort"), "repeatCount": 3, "delayBetweenPackets": 200},
     "name": "Send magic packet", "type": "n8n-nodes-wol.wakeOnLan", "typeVersion": 1, "position": [820, 360]},
    if_node("Caller waits?", [1040, 360], "caller-waits",
            "={{ $('Wake request').first().json.query.wait }}", "notEquals", "false", "string"),
    respond("Respond wake sent", [1260, 480], 202, "wake-sent", "woke: true"),
    {"parameters": {"resume": "timeInterval", "amount": cfg("pollSeconds"), "unit": "seconds"},
     "name": "Wait", "type": "n8n-nodes-base.wait", "typeVersion": 1.1, "position": [1260, 300],
     "webhookId": "wol-wake-on-demand-wait"},
    http("Poll health", [1480, 300]),
    if_node("Booted?", [1700, 300], "booted", "={{ $json.statusCode }}", "equals", 200),
    respond("Respond ready", [1920, 200], 200, "up", "woke: true"),
    if_node("Keep waiting?", [1920, 400], "keep-waiting", "={{ $runIndex }}", "lt", cfg("maxPolls")),
    respond("Respond timeout", [2140, 500], 504, "timeout",
            'hint: "magic packet sent but the host did not pass the health check in time"'),
]

edges = [
    ("Wake request", 0, "Config"), ("Config", 0, "Already up?"), ("Already up?", 0, "Up already"),
    ("Up already", 0, "Respond already up"), ("Up already", 1, "Send magic packet"),
    ("Send magic packet", 0, "Caller waits?"),
    ("Caller waits?", 0, "Wait"), ("Caller waits?", 1, "Respond wake sent"),
    ("Wait", 0, "Poll health"), ("Poll health", 0, "Booted?"),
    ("Booted?", 0, "Respond ready"), ("Booted?", 1, "Keep waiting?"),
    ("Keep waiting?", 0, "Wait"), ("Keep waiting?", 1, "Respond timeout"),
]
conns = {}
for src, idx, dst in edges:
    m = conns.setdefault(src, {"main": []})["main"]
    while len(m) <= idx:
        m.append([])
    m[idx].append({"node": dst, "type": "main", "index": 0})

wf = {"id": "wolWakeOnDemand01", "name": "Wake on demand (WoL)", "nodes": nodes, "connections": conns,
      "settings": {"executionOrder": "v1"}, "active": False}

out = json.dumps(wf, indent=2) + "\n"
if a.output == "-":
    sys.stdout.write(out)
else:
    with open(a.output, "w") as f:
        f.write(out)
