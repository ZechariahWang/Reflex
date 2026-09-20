#!/usr/bin/env bash
# Runs on the laptop: rents one Lambda GPU instance, uploads the code, the dataset, the skill
# and the training notes, starts setup.sh there, and opens the local tmux session `htn-train`
# (windows: watch = watchdog.sh, train / agent / work = the remote tmux sessions).
# KEEP THE LAPTOP AWAKE AND ONLINE: the watchdog here is the only thing that stops the billing.
#
#   policy/lambda/launch.sh                  # the rental of docs/notes/training/plan.md
#   policy/lambda/launch.sh --smoke-scripts  # no agent: 50 steps on a fake dataset, 1 h cap
#   policy/lambda/launch.sh --smoke          # the agent with a plan of two 50-step variants
#   policy/lambda/launch.sh --dry-run        # the confirm screen and the capacity, no launch
#   policy/lambda/launch.sh --no-watch       # no local tmux: start watchdog.sh yourself
#
# Settings: policy/lambda/.env (see .env.example). Design: docs/specs/lambda-training-design.md.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

mode=full dry_run=0 watch=1
for arg in "$@"; do
  case "$arg" in
    --smoke-scripts) mode=smoke-scripts ;;
    --smoke) mode=smoke ;;
    --dry-run) dry_run=1 ;;
    --no-watch) watch=0 ;;
    *) echo "error: unknown argument $arg" >&2; exit 2 ;;
  esac
done

require LAMBDA_API_KEY
require LAMBDA_INSTANCE_TYPE
require LAMBDA_SSH_KEY_NAME
require LAMBDA_SSH_KEY_PATH
[[ -f "$SSH_KEY_PATH" ]] || { echo "error: no ssh private key at $SSH_KEY_PATH (LAMBDA_SSH_KEY_PATH)" >&2; exit 1; }
[[ "$mode" == smoke-scripts ]] || require CLAUDE_CODE_OAUTH_TOKEN
max_hours="${LAMBDA_MAX_HOURS:-4}"
plan="$REPO_ROOT/docs/notes/training/plan.md"
if [[ "$mode" == full ]]; then
  require LAMBDA_DATASET
  dataset="$LAMBDA_DATASET"
  info="$REPO_ROOT/policy/datasets/$dataset/meta/info.json"
  [[ -f "$info" ]] || { echo "error: $info is absent: LAMBDA_DATASET must name a LeRobot dataset in policy/datasets/" >&2; exit 1; }
  [[ -f "$plan" ]] || { echo "error: $plan is absent: write the plan before a rental" >&2; exit 1; }
  episodes="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['total_episodes'])" "$info")"
else
  dataset=synth episodes="made on the instance" max_hours=1  # setup.sh runs synth_dataset.py there
fi

list="$(instances)" || { echo "error: GET /instances failed - run check_key.sh" >&2; exit 1; }
if [[ -n "$list" ]]; then
  echo "error: the account has an instance that bills; these scripts expect one rental at a time:" >&2
  echo "$list" >&2
  exit 1
fi

rm -f "$SCRIPT_DIR/.rental"  # of a rental that is over

# One rsync, from the repo root, so every path lands at the same place under ~/htn
uploads=(policy .claude/skills/exo-trainer docs/notes/training)
RSYNC_UP=(rsync -a --relative
  --exclude=.env --exclude=.venv --exclude=__pycache__ --exclude='*.egg-info' --exclude=.pytest_cache
  --exclude=/policy/outputs --exclude=/policy/logs
  --include="/policy/datasets/$dataset/" --exclude='/policy/datasets/*'
  --exclude=/policy/lambda/.rental --exclude=/policy/lambda/.watchdog.lock --exclude='PULL-FAILED-*')
listing="$(cd "$REPO_ROOT" && "${RSYNC_UP[@]}" -n --out-format='%l %n' "${uploads[@]}" "$(mktemp -d)/")"
if grep -E '(^|/)\.env$' <<< "$(awk '{print $2}' <<< "$listing")"; then
  echo "error: an .env file is in the upload set (above). Nothing is launched." >&2
  exit 1
fi

price="$(api instance-types | itype="$LAMBDA_INSTANCE_TYPE" python3 -c "
import json, os, sys
info = json.load(sys.stdin)['data'].get(os.environ['itype'])
if info is None:
    sys.exit('unknown instance type: ' + os.environ['itype'])
print(info['instance_type']['price_cents_per_hour'])
")" || exit 1
echo "Mode:      $mode"
echo "Instance:  $LAMBDA_INSTANCE_TYPE${LAMBDA_REGION:+ in $LAMBDA_REGION}, \$$(( price / 100 )).$(printf '%02d' $(( price % 100 )))/h"
echo "Cap:       $max_hours h, so at most \$$(( price * max_hours / 100 )) (the watchdog terminates at the cap)"
echo "Dataset:   $dataset ($episodes episodes)"
echo "Upload to ~/$REMOTE_DIR:"
for p in "policy/datasets/$dataset" "${uploads[@]}"; do
  awk -v p="$p/" 'index($2, p) == 1 { n += $1 } END { printf "  %8.1f MB  %s\n", n / 1e6, p }' <<< "$listing"
done
echo "  (policy is with that dataset, and without .venv, outputs, logs and the other datasets)"

region=""
resolve_region() {
  region="$(api instance-types | itype="$LAMBDA_INSTANCE_TYPE" want="${LAMBDA_REGION:-}" python3 -c "
import json, os, sys
regions = [r['name'] for r in json.load(sys.stdin)['data'][os.environ['itype']].get('regions_with_capacity_available', [])]
want = os.environ['want']
print((want if want in regions else '') if want else (regions[0] if regions else ''))
")" || region=""
}
if [[ "$dry_run" == 1 ]]; then
  resolve_region
  echo "[dry-run] capacity now: ${region:-none}. Nothing is launched."
  exit 0
fi
if [[ -t 0 ]]; then
  read -r -p "This starts the billing. Launch? [y/N] " reply
  [[ "$reply" =~ ^[Yy] ]] || { echo "No launch."; exit 1; }
fi

notify() { command -v notify-send >/dev/null 2>&1 && notify-send "htn launch" "$1" 2>/dev/null || true; printf '\a' >&2; }

# Sets instance_id. Returns 1 if the capacity went away between the check and the launch.
launch_instance() {
  local resp rc=0
  resp="$(curl -s --max-time 60 -u "${LAMBDA_API_KEY}:" "$API/instance-operations/launch" -H "Content-Type: application/json" \
    -d "{\"region_name\":\"$region\",\"instance_type_name\":\"$LAMBDA_INSTANCE_TYPE\",\"ssh_key_names\":[\"$LAMBDA_SSH_KEY_NAME\"],\"name\":\"htn-train\"}")"
  instance_id="$(resp="$resp" python3 -c "
import json, os, sys
raw = os.environ['resp']
try:
    d = json.loads(raw)
except json.JSONDecodeError:  # the CDN (rate limit), not Lambda: try again
    sys.stderr.write('no JSON from the launch API:\n' + raw[:500] + '\n'); sys.exit(1)
err = d.get('error')
if err:
    code, msg = err.get('code', ''), str(err.get('message', err))
    if 'not-available' in code or 'capacity' in msg.lower():
        sys.exit(1)
    sys.stderr.write('launch failed: ' + code + ': ' + msg + '\n'); sys.exit(2)
ids = d.get('data', {}).get('instance_ids') or []
if not ids:
    sys.stderr.write('the launch gave no instance id:\n' + raw[:500] + '\n'); sys.exit(2)
print(ids[0])
")" || rc=$?
  [[ "$rc" == 0 ]] && return 0
  [[ "$rc" == 1 ]] && return 1
  exit 1
}

poll="${LAMBDA_CAPACITY_POLL_INTERVAL:-30}"
start="$(date +%s)"
while :; do
  resolve_region
  if [[ -z "$region" ]]; then
    echo "no capacity for $LAMBDA_INSTANCE_TYPE yet ($(( $(date +%s) - start ))s) - next try in ${poll}s (Ctrl-C to stop)"
    sleep "$poll"
    continue
  fi
  echo "Launching in $region..."
  launch_instance && break
  echo "the capacity in $region went away before the launch - polling again"
  sleep "$poll"
done
launch_epoch="$(date +%s)"
write_rental() {
  printf 'LAMBDA_INSTANCE_ID=%s\nLAMBDA_INSTANCE_IP=%s\nLAMBDA_LAUNCH_EPOCH=%s\nRENTAL_MAX_HOURS=%s\n' \
    "$instance_id" "${ip:-}" "$launch_epoch" "$max_hours" > "$SCRIPT_DIR/.rental"
}
ip=""
write_rental  # before anything can fail: terminate.sh finds the instance from here on
notify "$LAMBDA_INSTANCE_TYPE launched in $region"
echo "Instance $instance_id. If this script dies: policy/lambda/terminate.sh"

echo -n "Waiting for boot"
for _ in $(seq 1 120); do
  read -r status ip < <(api "instances/$instance_id" \
    | python3 -c "import json,sys; d=json.load(sys.stdin)['data']; print(d.get('status',''), d.get('ip') or '')") || true
  [[ "${status:-}" == active && -n "$ip" ]] && break
  echo -n "."; sleep 10
done
echo
[[ -n "$ip" ]] || { notify "the instance never became active"; echo "error: instance $instance_id never became active. It may bill: run policy/lambda/terminate.sh" >&2; exit 1; }
write_rental
echo -n "Active at $ip. Waiting for ssh"
for _ in $(seq 1 60); do
  ssh "${SSH_OPTS[@]}" "$SSH_USER@$ip" true 2>/dev/null && break
  echo -n "."; sleep 5
done
echo
remote_markers="$REMOTE_DIR/policy/lambda"
# ponytail: rule 1 of the watchdog counts from this touch, so an upload of more than 30 min
# gets the instance terminated; start watchdog.sh by hand with a larger --timeout for that.
ssh "${SSH_OPTS[@]}" "$SSH_USER@$ip" "mkdir -p $remote_markers && touch $remote_markers/.watchdog-alive"

if [[ "$watch" == 1 ]] && command -v tmux >/dev/null 2>&1; then
  sess=htn-train; n=1
  while tmux has-session -t "$sess" 2>/dev/null; do sess="htn-train-$n"; n=$((n + 1)); done
  rssh="ssh -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=15 -i '$SSH_KEY_PATH' $SSH_USER@$ip"
  tmux new-session -d -s "$sess" -n watch "'$SCRIPT_DIR/watchdog.sh'; exec bash"
  for pair in train:train agent:experimenter work:work; do
    tmux new-window -t "$sess" -n "${pair%%:*}" \
      "$rssh -t 'until tmux has-session -t ${pair##*:} 2>/dev/null; do echo \"waiting for the remote tmux ${pair##*:}...\"; sleep 5; done; exec tmux attach -t ${pair##*:}'; exec bash"
  done
  tmux select-window -t "$sess:watch"
  echo "Local tmux session '$sess' is up: tmux attach -t $sess"
else
  echo "NO WATCHDOG IS RUNNING. Start policy/lambda/watchdog.sh now, or the instance bills with no limit."
fi

echo "Uploading..."
(cd "$REPO_ROOT" && "${RSYNC_UP[@]}" --info=progress2 -e "ssh ${SSH_OPTS[*]}" "${uploads[@]}" "$SSH_USER@$ip:$REMOTE_DIR/")
[[ "$mode" == smoke ]] && scp -q "${SSH_OPTS[@]}" "$SCRIPT_DIR/smoke_plan.md" "$SSH_USER@$ip:$REMOTE_DIR/docs/notes/training/plan.md"
# .env stays here, so the facts of the rental that the agent needs go up in their own file
printf 'MODE=%s\nDATASET=%s\nINSTANCE_TYPE=%s\nMAX_HOURS=%s\nLAUNCH_UTC=%s\n' \
  "$mode" "$dataset" "$LAMBDA_INSTANCE_TYPE" "$max_hours" "$(date -u -d "@$launch_epoch" +%Y-%m-%dT%H:%M:%SZ)" \
  | ssh "${SSH_OPTS[@]}" "$SSH_USER@$ip" "cat > $remote_markers/rental.env"

# The token goes up in a file, never on a command line (the process list of the instance)
env_file="$(mktemp)"
trap 'rm -f "$env_file"' EXIT
[[ "$mode" == smoke-scripts ]] || printf 'export CLAUDE_CODE_OAUTH_TOKEN=%q\n' "$CLAUDE_CODE_OAUTH_TOKEN" > "$env_file"
scp -q "${SSH_OPTS[@]}" "$env_file" "$SSH_USER@$ip:setup.env"
ssh "${SSH_OPTS[@]}" "$SSH_USER@$ip" "
  chmod 600 ~/setup.env; touch $remote_markers/.watchdog-alive
  command -v tmux >/dev/null || { sudo apt-get update -qq && sudo apt-get install -y -qq tmux; }
  tmux new-session -d -s train '. ~/setup.env; rm -f ~/setup.env; ~/$remote_markers/run_logged.sh setup bash ~/$remote_markers/setup.sh; exec bash -l'"

echo
echo "Launched: instance $instance_id at $ip, setup runs in the remote tmux 'train'."
echo "Watch it: tmux attach -t ${sess:-htn-train}. Stop it now: policy/lambda/terminate.sh"
