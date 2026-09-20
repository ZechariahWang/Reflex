#!/usr/bin/env bash
# Runs ON THE LAPTOP for the whole rental: pulls the artifacts home and terminates the instance.
# The Lambda API key stays here, so nothing on the instance can launch, keep or terminate one.
# If this machine sleeps or goes offline, NOTHING stops the billing.
#
#   policy/lambda/watchdog.sh                          # launch.sh starts it in tmux `htn-train`
#   policy/lambda/watchdog.sh --terminate-cmd "echo"   # dry run: no real terminate
#
# It reads only files, all in ~/htn/policy/lambda/ on the instance; there is no process
# detection. One probe every --interval seconds, rules in this order:
#
#   5  time since launch >= LAMBDA_MAX_HOURS             final pull, terminate
#   4  time since launch >= cap - 20 min                 write .watchdog-cap-warning once
#   2  no ssh for --unreachable-timeout, API says active terminate, write PULL-FAILED-<UTC>
#   3  .watchdog-terminate newer than the first probe    final pull, terminate
#   6  .watchdog-fetch exists                            pull, delete the marker
#   7  --pull-interval since the last pull               pull
#   1  .watchdog-alive older than --timeout              final pull, terminate
#
# .watchdog-alive is touched by the agent and by run_logged.sh while its log grows. The final
# pull has a time limit and two retries; the terminate happens whether it succeeds or not, and
# a final pull that never succeeded leaves PULL-FAILED-<UTC> next to this script.
#
# The rental (instance id, ip, launch time, cap) is in .rental, written by launch.sh, so a
# restarted watchdog keeps the same cap. Design: docs/specs/lambda-training-design.md.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for f in "$SCRIPT_DIR/.env" "$SCRIPT_DIR/.rental"; do
  if [[ -f "$f" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$f"
    set +a
  fi
done

timeout=1800
interval=60
unreachable_timeout=900
pull_interval=300
pull_timeout=900
pull_retry_wait=120
cap_warning=1200
terminate_cmd=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --timeout) timeout="$2"; shift 2 ;;
    --interval) interval="$2"; shift 2 ;;
    --unreachable-timeout) unreachable_timeout="$2"; shift 2 ;;
    --pull-interval) pull_interval="$2"; shift 2 ;;
    --pull-timeout) pull_timeout="$2"; shift 2 ;;
    --pull-retry-wait) pull_retry_wait="$2"; shift 2 ;;
    --terminate-cmd) terminate_cmd="$2"; shift 2 ;;
    *) echo "error: unknown flag $1" >&2; exit 1 ;;
  esac
done

# Two watchdogs on one instance double the terminate risk and mix their logs
exec 9>"$SCRIPT_DIR/.watchdog.lock"
if ! flock -n 9; then
  echo "error: another watchdog.sh is already running (it holds $SCRIPT_DIR/.watchdog.lock)" >&2
  exit 1
fi

instance_id="${LAMBDA_INSTANCE_ID:-}"
instance_ip="${LAMBDA_INSTANCE_IP:-}"
launch_epoch="${LAMBDA_LAUNCH_EPOCH:-}"
if [[ -z "$instance_id" || -z "$instance_ip" || -z "$launch_epoch" ]]; then
  echo "error: no rental in $SCRIPT_DIR/.rental (launch.sh writes LAMBDA_INSTANCE_ID, LAMBDA_INSTANCE_IP and LAMBDA_LAUNCH_EPOCH and RENTAL_MAX_HOURS there)" >&2
  exit 1
fi
cap=$(( ${RENTAL_MAX_HOURS:-${LAMBDA_MAX_HOURS:-4}} * 3600 ))
markers="${LAMBDA_REMOTE_DIR:-htn}/policy/lambda"
ssh_user="${LAMBDA_SSH_USER:-ubuntu}"
echo "Watching instance $instance_id at $instance_ip (alive timeout ${timeout}s, cap ${cap}s, $(( $(date +%s) - launch_epoch ))s since the launch)"

# ConnectTimeout bounds only the connect; the keepalives end a connection that goes dead
SSH_CMD=(ssh -o ConnectTimeout=10 -o BatchMode=yes -o StrictHostKeyChecking=accept-new
  -o ServerAliveInterval=15 -o ServerAliveCountMax=2
  ${LAMBDA_SSH_KEY_PATH:+-i "$LAMBDA_SSH_KEY_PATH"} "${ssh_user}@${instance_ip}")
# Test hook: WATCHDOG_SSH_OVERRIDE="bash -c" runs the probes in a local shell
if [[ -n "${WATCHDOG_SSH_OVERRIDE:-}" ]]; then
  read -ra SSH_CMD <<< "$WATCHDOG_SSH_OVERRIDE"
fi
remote() { timeout 30 "${SSH_CMD[@]}" "$1" 2>/dev/null; }

probe_snippet="
  date +%s
  stat -c %Y '$markers/.watchdog-alive' 2>/dev/null || echo 0
  stat -c %Y '$markers/.watchdog-terminate' 2>/dev/null || echo 0
  [ -e '$markers/.watchdog-fetch' ] && echo 1 || echo 0
"

run_pull() { timeout "$pull_timeout" "$SCRIPT_DIR/pull.sh" "$instance_ip"; }

pull_failed() {
  local marker
  marker="$SCRIPT_DIR/PULL-FAILED-$(date -u +%Y%m%dT%H%M%SZ)"
  printf 'no final pull from %s (instance %s); terminated all the same\nreason: %s\n%s\n' \
    "$instance_ip" "$instance_id" "$1" "$2" > "$marker"
  echo "watchdog: NO FINAL PULL - wrote $marker" >&2
}

# $2: 0 = no final pull (an instance with no ssh has nothing to give)
terminate() {
  local reason="$1" do_pull="${2:-1}" log attempt ok=0
  echo "watchdog: $reason - terminating instance $instance_id"
  if [[ "$do_pull" -eq 1 ]]; then
    log="$(mktemp)"
    for attempt in 1 2 3; do
      echo "watchdog: final pull, attempt $attempt of 3..."
      if run_pull 2>&1 | tee "$log"; then ok=1; break; fi
      echo "watchdog: the final pull failed or passed ${pull_timeout}s" >&2
      if (( attempt < 3 )); then sleep "$pull_retry_wait"; fi
    done
    (( ok )) || pull_failed "$reason" "$(tail -20 "$log")"
    rm -f "$log"
  else
    pull_failed "$reason" "the instance did not answer ssh"
  fi
  export LAMBDA_INSTANCE_ID="$instance_id"
  if [[ -n "$terminate_cmd" ]]; then
    exec bash -c "$terminate_cmd"
  fi
  exec "$SCRIPT_DIR/terminate.sh"
}

instance_still_active() {
  [[ -n "${LAMBDA_API_KEY:-}" ]] || return 0  # no API: assume that it bills
  local status
  status="$(curl -sf --max-time 30 -u "${LAMBDA_API_KEY}:" \
    "https://cloud.lambdalabs.com/api/v1/instances/${instance_id}" \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['data']['status'])" 2>/dev/null)" || return 0
  [[ "$status" == "active" ]]
}

watch_start=""  # remote clock at the first good probe: older markers are from another rental
unreachable_since=""
last_pull=0
warned=0

while true; do
  since_launch=$(( $(date +%s) - launch_epoch ))
  if (( since_launch >= cap )); then
    terminate "the cap of $(( cap / 3600 )) h since the launch is reached"
  fi
  # The timeout is the hard limit of one probe: a hung ssh counts as one interval of failure
  if output="$(timeout "$interval" "${SSH_CMD[@]}" "$probe_snippet" 2>/dev/null)"; then
    unreachable_since=""
    { read -r remote_now; read -r alive_mtime; read -r terminate_mtime; read -r fetch; } <<< "$output"
    watch_start="${watch_start:-$remote_now}"
    if (( warned == 0 && since_launch >= cap - cap_warning )) && remote "touch '$markers/.watchdog-cap-warning'"; then
      warned=1
      echo "watchdog: [$(date +%H:%M:%S)] $(( (cap - since_launch) / 60 )) min to the cap - wrote .watchdog-cap-warning"
    fi
    if (( terminate_mtime >= watch_start )); then
      terminate "the instance asked for it with .watchdog-terminate"
    fi
    if (( fetch == 1 || $(date +%s) - last_pull >= pull_interval )); then
      echo "watchdog: [$(date +%H:%M:%S)] pull$( (( fetch == 1 )) && echo ' (asked for with .watchdog-fetch)')..."
      run_pull || echo "watchdog: the pull failed or passed ${pull_timeout}s - next try in ${pull_interval}s" >&2
      last_pull="$(date +%s)"
      # The marker goes whether or not the pull worked: the receipt is the sign of success
      if (( fetch == 1 )); then remote "rm -f '$markers/.watchdog-fetch'" || true; fi
    fi
    if (( alive_mtime > remote_now + 60 )); then
      # A future date would keep the instance with no end: make it one normal touch
      remote "touch '$markers/.watchdog-alive'" || true
      alive_mtime="$remote_now"
    fi
    # No file yet (launch.sh is still uploading): count from the first probe
    (( alive_mtime == 0 )) && alive_mtime="$watch_start"
    remaining=$(( alive_mtime + timeout - remote_now ))
    if (( remaining <= 0 )); then
      terminate "no touch of .watchdog-alive for ${timeout}s"
    fi
    echo "watchdog: [$(date +%H:%M:%S)] alive $(( remote_now - alive_mtime ))s ago - terminate in ${remaining}s with no touch, cap in $(( (cap - since_launch) / 60 )) min"
  else
    if ! instance_still_active; then
      echo "watchdog: the instance is not active any more - done"
      exit 0
    fi
    now="$(date +%s)"
    unreachable_since="${unreachable_since:-$now}"
    echo "watchdog: [$(date +%H:%M:%S)] no ssh for $(( now - unreachable_since ))s (the API says active) - terminate at ${unreachable_timeout}s"
    if (( now - unreachable_since >= unreachable_timeout )); then
      terminate "no ssh for ${unreachable_timeout}s while it bills" 0
    fi
  fi
  sleep "$interval"
done
