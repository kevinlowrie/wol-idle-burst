#!/usr/bin/env bash
# Unit tests for bin/idle-poweroff. No root, no real hardware: external commands are shimmed.
set -u
here=$(cd "$(dirname "$0")" && pwd)
script=$here/../bin/idle-poweroff
pass=0 fail=0

setup() {
  T=$(mktemp -d)
  mkdir -p "$T/shims" "$T/proc" "$T/state"
  for c in nvidia-smi ss pgrep virsh podman loginctl logger; do
    cat >"$T/shims/$c" <<'SH'
#!/usr/bin/env bash
# Shim: prints $SHIMDIR/<cmd>[.<key>] if it exists; pgrep exits 1 unless a matching file exists.
cmd=$(basename "$0"); key=""
case $cmd in
  ss)     key=$(printf '%s' "${@: -1}" | tr -dc '0-9') ;;
  pgrep)  key=$(printf '%s' "${@: -1}" | tr -c 'A-Za-z0-9' '_') ;;
  logger) printf '%s\n' "$*" >>"$SHIMDIR/logger.log"; exit 0 ;;
esac
f="$SHIMDIR/$cmd${key:+.$key}"
if [ -e "$f" ]; then cat "$f"; exit 0; fi
[ "$cmd" = pgrep ] && exit 1
exit 0
SH
    chmod +x "$T/shims/$c"
  done
  echo "50000.00 100000.00" >"$T/proc/uptime"
  echo "0.10 0.10 0.10 1/100 1" >"$T/proc/loadavg"
  : >"$T/conf"
  export SHIMDIR=$T PATH="$T/shims:$PATH" \
    IDLE_POWEROFF_CONF=$T/conf IDLE_POWEROFF_STATE_DIR=$T/state IDLE_POWEROFF_PROC_DIR=$T/proc \
    IDLE_POWEROFF_CMD="touch $T/poweroff-called"
}

run() { "$script" "$@" 2>&1; }

assert() { # name, command...
  local name=$1; shift
  if "$@"; then pass=$((pass + 1)); echo "ok   - $name"; else fail=$((fail + 1)); echo "FAIL - $name"; fi
}
check() { # name, condition-exit-status
  if [ "$2" -eq 0 ]; then pass=$((pass + 1)); echo "ok   - $1"; else fail=$((fail + 1)); echo "FAIL - $1"; fi
}
contains() { grep -q -- "$2" <<<"$1"; }

t() { setup; "$@"; rm -rf "$T"; }

test_idle_when_quiet() { out=$(run status); contains "$out" '^IDLE'; check "quiet host reports IDLE" $?; }

test_boot_grace() {
  echo "60.00 10.00" >"$T/proc/uptime"
  out=$(run status); contains "$out" 'boot grace'; check "recent boot is busy" $?
}

test_gpu_busy() {
  printf '2\n87\n' >"$T/nvidia-smi"
  out=$(run status); contains "$out" 'GPU utilization'; check "GPU above threshold is busy" $?
}

test_gpu_low() {
  printf '2\n4\n' >"$T/nvidia-smi"
  out=$(run status); contains "$out" '^IDLE'; check "GPU below threshold is idle" $?
}

test_client_connected() {
  echo 'WATCH_PORTS="8000 8088"' >"$T/conf"
  echo "ESTAB 0 0 10.0.0.1:8088 10.0.0.9:5555" >"$T/ss.8088"
  out=$(run status); contains "$out" 'client connected on :8088'; check "client on watched port is busy" $?
}

test_client_other_port() {
  echo 'WATCH_PORTS="8000"' >"$T/conf"
  echo "ESTAB x" >"$T/ss.8088"
  out=$(run status); contains "$out" '^IDLE'; check "client on unwatched port is ignored" $?
}

test_load() {
  echo "0.1 15.0 9.0 1/100 1" >"$T/proc/loadavg"
  out=$(run status); contains "$out" 'load5'; check "high 5-min load is busy" $?
}

test_runner() {
  echo 1234 >"$T/pgrep.Runner_Worker"
  out=$(run status); contains "$out" 'GitHub Actions'; check "Actions job is busy" $?
}

test_apt() {
  echo 99 >"$T/pgrep.apt_get_apt_dpkg"
  out=$(run status); contains "$out" 'package manager'; check "apt/dpkg is busy" $?
}

test_vm() {
  echo " 1  vm1  running" >"$T/virsh"
  out=$(run status); contains "$out" 'libvirt VM'; check "running VM is busy" $?
}

test_containers() {
  echo "IGNORE_CONTAINERS_MATCHING='^llama-'" >"$T/conf"
  printf 'llama-0\nllama-1\n' >"$T/podman"
  out=$(run status); contains "$out" '^IDLE'; check "ignored containers do not block" $?
  printf 'llama-0\nrender-job\n' >"$T/podman"
  out=$(run status); contains "$out" 'container running'; check "other container is busy" $?
}

test_session() {
  echo "1 1000 user seat0" >"$T/loginctl"
  out=$(run status); contains "$out" 'logged-in session'; check "login session is busy" $?
  echo "IGNORE_SESSIONS=1" >"$T/conf"
  out=$(run status); contains "$out" '^IDLE'; check "IGNORE_SESSIONS=1 ignores sessions" $?
}

test_inhibit() {
  echo "INHIBIT_FILE=$T/no-autooff" >"$T/conf"; touch "$T/no-autooff"
  out=$(run status); contains "$out" 'inhibit file'; check "inhibit file blocks" $?
}

test_keepawake() {
  run keepawake 2 >/dev/null
  out=$(run status); contains "$out" 'keepawake active'; check "keepawake blocks" $?
  touch -d '3 hours ago' "$T/state/keepawake"
  out=$(run status); contains "$out" '^IDLE'; check "keepawake expires" $?
}

test_poweroff_after_idle_window() {
  printf 'DRY_RUN=0\nIDLE_MINUTES=30\n' >"$T/conf"
  run run >/dev/null
  assert "first idle pass does not power off" [ ! -e "$T/poweroff-called" ]
  echo $(($(date +%s) - 31 * 60)) >"$T/state/idle_since"
  run run >/dev/null
  assert "powers off after IDLE_MINUTES" [ -e "$T/poweroff-called" ]
}

test_not_before_window() {
  printf 'DRY_RUN=0\nIDLE_MINUTES=30\n' >"$T/conf"
  echo $(($(date +%s) - 10 * 60)) >"$T/state/idle_since"
  run run >/dev/null
  assert "no poweroff inside idle window" [ ! -e "$T/poweroff-called" ]
}

test_dry_run() {
  printf 'DRY_RUN=1\nIDLE_MINUTES=30\n' >"$T/conf"
  echo $(($(date +%s) - 60 * 60)) >"$T/state/idle_since"
  run run >/dev/null
  [ ! -e "$T/poweroff-called" ] && grep -q 'DRY_RUN' "$T/logger.log"; check "DRY_RUN logs but never powers off" $?
}

test_busy_resets_window() {
  printf 'DRY_RUN=0\nIDLE_MINUTES=30\n' >"$T/conf"
  echo $(($(date +%s) - 60 * 60)) >"$T/state/idle_since"
  printf '90\n' >"$T/nvidia-smi"
  run run >/dev/null
  assert "activity resets the idle window" [ ! -e "$T/poweroff-called" ] && [ ! -e "$T/state/idle_since" ]
}

for fn in $(declare -F | awk '$3 ~ /^test_/ {print $3}'); do t "$fn"; done
echo; echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
