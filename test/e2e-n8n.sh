#!/usr/bin/env bash
# End-to-end test: real n8n (podman) + real n8n-nodes-wol from npm + a fake sleeping host.
# Verifies the magic packet bytes, and the three workflow outcomes: already up / woke and came up / timed out.
# Needs: podman, python3, curl, outbound access to the container registry and npm. No root.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
root=$here/..

N8N_IMAGE=${N8N_IMAGE:-docker.io/n8nio/n8n:2.44.6}
NODE_IMAGE=${NODE_IMAGE:-docker.io/library/node:22-alpine}
WOL_PKG=${WOL_PKG:-n8n-nodes-wol@0.1.1}
N8N_PORT=${N8N_PORT:-15678}
TEST_MAC=02:00:00:00:00:01
TEST_BROADCAST=${TEST_BROADCAST:-127.255.255.255}   # use your LAN's directed broadcast to test the real wire path
UDP_PORT=40009
HEALTH_PORT=48088
NAME=wol-e2e-n8n

D=$(mktemp -d)
pids=()
cleanup() {
  podman rm -f "$NAME" >/dev/null 2>&1 || true
  for p in "${pids[@]:-}"; do [ -n "$p" ] && kill "$p" 2>/dev/null || true; done
  rm -rf "$D"
}
trap cleanup EXIT

pass=0 fail=0
assert() { # name, command...
  local name=$1; shift
  if "$@"; then pass=$((pass + 1)); echo "ok   - $name"; else fail=$((fail + 1)); echo "FAIL - $name"; fi
}
body_has() { [ "$code" = "$1" ] && grep -q "$2" <<<"$body"; }

# shellcheck disable=SC2054
ctr=(podman run --rm --userns=keep-id:uid=1000,gid=1000 --user 1000:1000 -v "$D/n8n:/home/node/.n8n")

mkdir -p "$D/n8n/nodes"
echo "== installing $WOL_PKG into n8n's custom nodes dir"
"${ctr[@]}" -w /home/node/.n8n/nodes -e npm_config_cache=/tmp/.npm "$NODE_IMAGE" \
  sh -c "npm init -y >/dev/null && npm install --no-audit --no-fund $WOL_PKG" | tail -2

python3 "$root/tools/gen_workflow.py" --mac "$TEST_MAC" --broadcast "$TEST_BROADCAST" --wol-port "$UDP_PORT" \
  --health-url "http://127.0.0.1:$HEALTH_PORT/health" --poll-seconds 2 --max-polls 6 -o "$D/wf.json"

echo "== importing + publishing workflow"
"${ctr[@]}" -v "$D/wf.json:/wf.json:ro" "$N8N_IMAGE" import:workflow --input=/wf.json 2>&1 | tail -2
"${ctr[@]}" "$N8N_IMAGE" publish:workflow --id=wolWakeOnDemand01 2>&1 | tail -2

echo "== starting n8n on 127.0.0.1:$N8N_PORT"
podman run -d --name "$NAME" --network host --userns=keep-id:uid=1000,gid=1000 --user 1000:1000 \
  -v "$D/n8n:/home/node/.n8n" \
  -e N8N_PORT="$N8N_PORT" -e N8N_LISTEN_ADDRESS=127.0.0.1 -e N8N_DIAGNOSTICS_ENABLED=false \
  -e N8N_VERSION_NOTIFICATIONS_ENABLED=false -e N8N_PERSONALIZATION_ENABLED=false -e N8N_LOG_LEVEL=debug \
  "$N8N_IMAGE" >/dev/null
# /healthz goes green before published workflows are activated; wait for the webhook registration itself.
# (capture first: `podman logs | grep -q` can die of SIGPIPE under pipefail and look like "not found")
registered() { local logs; logs=$(podman logs "$NAME" 2>&1); grep -q 'Added webhook "Wake request"' <<<"$logs"; }
for _ in $(seq 90); do registered && break; sleep 1; done
registered || { echo "webhook never registered"; podman logs "$NAME" 2>&1 | tail -30; exit 1; }

url=http://127.0.0.1:$N8N_PORT/webhook/wake-on-demand
fake() { python3 -I "$here/fake_host.py" --mac "$TEST_MAC" --udp-port "$UDP_PORT" --health-port "$HEALTH_PORT" --events "$D/events" "$@" & pids+=($!); sleep 0.7; }
stop_fake() { kill "${pids[@]}" 2>/dev/null || true; wait 2>/dev/null || true; pids=(); sleep 0.5; }
count() { { grep -c "\"event\": \"$1\"" "$D/events" 2>/dev/null || true; } | head -1; }
call() { curl -s -m 40 -o "$D/body" -w '%{http_code}' -X POST "$url$1"; }

echo "== scenario A: host already up -> no packet"
: >"$D/events"; fake --already-up --lifetime 20
code=$(call ""); body=$(cat "$D/body")
assert "A: returns 200 woke:false ($code $body)" body_has 200 '"woke":false'
assert "A: no magic packet sent" [ "$(count magic-packet)" = 0 ]
stop_fake

echo "== scenario B: host asleep -> wake -> boots after 3 s"
: >"$D/events"; fake --boot-delay 3 --lifetime 30
code=$(call ""); body=$(cat "$D/body")
assert "B: returns 200 woke:true ($code $body)" body_has 200 '"woke":true'
assert "B: valid magic packet received ($(count magic-packet) x)" [ "$(count magic-packet)" -ge 1 ]
assert "B: no malformed packets" [ "$(count bad-packet)" = 0 ]
assert "B: workflow polled /health after boot" [ "$(count health-hit)" -ge 1 ]
stop_fake

echo "== scenario C: wake sent, host never boots -> 504"
: >"$D/events"; fake --no-boot --lifetime 30
code=$(call ""); body=$(cat "$D/body")
assert "C: returns 504 timeout ($code $body)" body_has 504 timeout
assert "C: magic packet was still sent" [ "$(count magic-packet)" -ge 1 ]
stop_fake

echo "== scenario D: ?wait=false -> 202 immediately"
: >"$D/events"; fake --no-boot --lifetime 15
code=$(call "?wait=false"); body=$(cat "$D/body")
assert "D: returns 202 wake-sent ($code $body)" body_has 202 wake-sent
stop_fake

echo; echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ] || { podman logs "$NAME" 2>&1 | tail -30; exit 1; }
