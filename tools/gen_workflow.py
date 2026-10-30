#!/usr/bin/env python3
"""Generate the n8n "wake on demand" workflow JSON.

The committed n8n/wake-on-demand.workflow.json is the output of this script with placeholder values.
Use the flags to bake your own host in, or just edit the "Config" node after importing.

The workflow has two entry points that share one body: the webhook (POST /webhook/<path>) and an
"Execute Workflow Trigger", so any other workflow can launch it with an Execute Workflow node.

With --caller it instead emits a small example workflow that calls the wake workflow from an
Execute Workflow node (use it as a template for your own jobs).
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
p.add_argument("--caller", choices=["manual", "webhook"], help="emit the example caller workflow instead (manual or webhook trigger)")
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


def result(name, pos, status, woke, code, hint=None):
    """Terminal state of a run. Every path ends here, then is answered (webhook) or returned (sub-workflow)."""
    rows = [assign("status", status, "string"), assign("woke", woke, "boolean"), assign("httpCode", code, "number")]
    if hint:
        rows.append(assign("hint", hint, "string"))
    return {"parameters": {"assignments": {"assignments": rows}, "options": {}},
            "name": name, "type": "n8n-nodes-base.set", "typeVersion": 3.4, "position": pos}


def assign(name, value, kind):
    return {"id": "cfg-" + name, "name": name, "value": value, "type": kind}


def set_node(name, pos, rows, keep_other=False):
    return {"parameters": {"assignments": {"assignments": [assign(n, v, k) for n, v, k in rows]},
                           "includeOtherFields": keep_other, "options": {}},
            "name": name, "type": "n8n-nodes-base.set", "typeVersion": 3.4, "position": pos}


def build_caller():
    trigger = ({"parameters": {}, "name": "Manual trigger", "type": "n8n-nodes-base.manualTrigger",
                "typeVersion": 1, "position": [0, 0]} if a.caller == "manual" else
               {"parameters": {"httpMethod": "POST", "path": "run-my-job", "responseMode": "lastNode", "options": {}},
                "name": "Webhook trigger", "type": "n8n-nodes-base.webhook", "typeVersion": 2, "position": [0, 0],
                "webhookId": "wol-example-caller"})
    nodes = [
        trigger,
        {"parameters": {"source": "database",
                        "workflowId": {"__rl": True, "value": "wolWakeOnDemand01", "mode": "id"},
                        "workflowInputs": {"mappingMode": "defineBelow", "value": {}, "matchingColumns": [],
                                           "schema": [], "attemptToConvertTypes": False, "convertFieldsToString": True},
                        "options": {"waitForSubWorkflow": True}},
         "name": "Wake the server", "type": "n8n-nodes-base.executeWorkflow", "typeVersion": 1.2,
         "position": [240, 0]},
        if_node("Is it up?", [480, 0], "is-up", "={{ $json.status }}", "equals", "up", "string"),
        {"parameters": {}, "name": "Do the work here", "type": "n8n-nodes-base.noOp", "typeVersion": 1,
         "position": [720, -100]},
        {"parameters": {"errorMessage": "={{ 'server did not come up: ' + $json.status }}"},
         "name": "Give up", "type": "n8n-nodes-base.stopAndError", "typeVersion": 1, "position": [720, 100]},
    ]
    edges = [(trigger["name"], 0, "Wake the server"), ("Wake the server", 0, "Is it up?"),
             ("Is it up?", 0, "Do the work here"), ("Is it up?", 1, "Give up")]
    return "Example: wake the server, then do a job", "wolExampleCaller01", nodes, edges


if a.caller:
    wf_name, wf_id, nodes, edges = build_caller()
else:
    wf_name, wf_id = "Wake on demand (WoL)", "wolWakeOnDemand01"
    nodes = [
        {"parameters": {"httpMethod": "POST", "path": a.webhook_path, "responseMode": "responseNode", "options": {}},
         "name": "Wake request", "type": "n8n-nodes-base.webhook", "typeVersion": 2, "position": [0, 160],
         "webhookId": "wol-wake-on-demand"},
        {"parameters": {"inputSource": "passthrough"}, "name": "Called by another workflow",
         "type": "n8n-nodes-base.executeWorkflowTrigger", "typeVersion": 1.1, "position": [0, 380]},
        set_node("From webhook", [200, 160],
                 [("wait", '={{ $json.query.wait !== "false" }}', "boolean"), ("viaWebhook", True, "boolean")]),
        set_node("From workflow", [200, 380],
                 [("wait", '={{ $json.wait !== false && $json.wait !== "false" }}', "boolean"),
                  ("viaWebhook", False, "boolean")]),
        {"parameters": {"assignments": {"assignments": [
            assign("mac", a.mac, "string"),
            assign("broadcastAddress", a.broadcast, "string"),
            assign("wolPort", a.wol_port, "number"),
            assign("healthUrl", a.health_url, "string"),
            assign("pollSeconds", a.poll_seconds, "number"),
            assign("maxPolls", a.max_polls, "number")]}, "includeOtherFields": True, "options": {}},
         "name": "Config", "type": "n8n-nodes-base.set", "typeVersion": 3.4, "position": [420, 270]},
        http("Already up?", [620, 270]),
        if_node("Up already", [820, 270], "up-already", "={{ $json.statusCode }}", "equals", 200),
        result("Result: already up", [1040, 120], "up", False, 200),
        {"parameters": {"macAddress": cfg("mac"), "broadcastAddress": cfg("broadcastAddress"),
                        "port": cfg("wolPort"), "repeatCount": 3, "delayBetweenPackets": 200},
         "name": "Send magic packet", "type": "n8n-nodes-wol.wakeOnLan", "typeVersion": 1, "position": [1040, 400]},
        if_node("Caller waits?", [1260, 400], "caller-waits",
                "={{ String($('Config').first().json.wait) }}", "notEquals", "false", "string"),
        result("Result: wake sent", [1480, 540], "wake-sent", True, 202),
        {"parameters": {"resume": "timeInterval", "amount": cfg("pollSeconds"), "unit": "seconds"},
         "name": "Wait", "type": "n8n-nodes-base.wait", "typeVersion": 1.1, "position": [1480, 340],
         "webhookId": "wol-wake-on-demand-wait"},
        http("Poll health", [1700, 340]),
        if_node("Booted?", [1920, 340], "booted", "={{ $json.statusCode }}", "equals", 200),
        result("Result: ready", [2140, 240], "up", True, 200),
        if_node("Keep waiting?", [2140, 440], "keep-waiting", "={{ $runIndex }}", "lt", cfg("maxPolls")),
        result("Result: timeout", [2360, 540], "timeout", True, 504,
               "magic packet sent but the host did not pass the health check in time"),
        if_node("Via webhook?", [2600, 300], "via-webhook", "={{ String($('Config').first().json.viaWebhook) }}",
                "equals", "true", "string"),
        {"parameters": {"respondWith": "json",
                        "responseBody": "={{ JSON.stringify({ status: $json.status, woke: $json.woke, hint: $json.hint }) }}",
                        "options": {"responseCode": "={{ $json.httpCode }}"}},
         "name": "Respond to webhook", "type": "n8n-nodes-base.respondToWebhook", "typeVersion": 1.1,
         "position": [2840, 200]},
        {"parameters": {}, "name": "Return to calling workflow", "type": "n8n-nodes-base.noOp", "typeVersion": 1,
         "position": [2840, 400]},
    ]
    edges = [
        ("Wake request", 0, "From webhook"), ("Called by another workflow", 0, "From workflow"),
        ("From webhook", 0, "Config"), ("From workflow", 0, "Config"),
        ("Config", 0, "Already up?"), ("Already up?", 0, "Up already"),
        ("Up already", 0, "Result: already up"), ("Up already", 1, "Send magic packet"),
        ("Send magic packet", 0, "Caller waits?"),
        ("Caller waits?", 0, "Wait"), ("Caller waits?", 1, "Result: wake sent"),
        ("Wait", 0, "Poll health"), ("Poll health", 0, "Booted?"),
        ("Booted?", 0, "Result: ready"), ("Booted?", 1, "Keep waiting?"),
        ("Keep waiting?", 0, "Wait"), ("Keep waiting?", 1, "Result: timeout"),
        ("Result: already up", 0, "Via webhook?"), ("Result: wake sent", 0, "Via webhook?"),
        ("Result: ready", 0, "Via webhook?"), ("Result: timeout", 0, "Via webhook?"),
        ("Via webhook?", 0, "Respond to webhook"), ("Via webhook?", 1, "Return to calling workflow"),
    ]

conns = {}
for src, idx, dst in edges:
    m = conns.setdefault(src, {"main": []})["main"]
    while len(m) <= idx:
        m.append([])
    m[idx].append({"node": dst, "type": "main", "index": 0})

wf = {"id": wf_id, "name": wf_name, "nodes": nodes, "connections": conns,
      "settings": {"executionOrder": "v1"}, "active": False}

out = json.dumps(wf, indent=2) + "\n"
if a.output == "-":
    sys.stdout.write(out)
else:
    with open(a.output, "w") as f:
        f.write(out)
