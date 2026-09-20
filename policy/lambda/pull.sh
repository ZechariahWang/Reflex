#!/usr/bin/env bash
# Runs on the laptop: rsync of the artifacts from the instance, then a receipt back to it.
#
#   policy/lambda/pull.sh [ip] [--dry-run]     # the ip comes from .rental if it is absent
#
# Comes home: policy/outputs/ (the checkpoints, without training_state/: a resume across
# rentals is out of scope and it is a third of each checkpoint), policy/logs/ and
# docs/notes/training/runs/. The watchdog calls this on a schedule, on .watchdog-fetch and
# before a terminate. After a pull, the size of each file AS IT IS HERE goes to
# ~/htn/policy/lambda/.pull-receipt: the instance has no other proof that its work is home.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

PATHS="policy/outputs policy/logs docs/notes/training/runs"
ip="${LAMBDA_INSTANCE_IP:-}"
dry=()
for arg in "$@"; do
  case "$arg" in
    --dry-run) dry=(-n) ;;
    -*) echo "error: unknown flag $arg" >&2; exit 1 ;;
    *) ip="$arg" ;;
  esac
done
[[ -n "$ip" ]] || { echo "error: no ip: pass it, or launch first (.rental)" >&2; exit 1; }

present="$(ssh "${SSH_OPTS[@]}" "$SSH_USER@$ip" "cd '$REMOTE_DIR' && for p in $PATHS; do [ -d \"\$p\" ] && echo \"\$p\"; done; true")"
if [[ -z "$present" ]]; then
  echo "Nothing to pull yet: none of $PATHS is on the instance."
  exit 0
fi
while IFS= read -r p; do
  echo "[$(date +%H:%M:%S)] pull $p"
  rsync -azi "${dry[@]}" --info=stats1 --exclude=training_state -e "ssh ${SSH_OPTS[*]}" \
    --relative "$SSH_USER@$ip:$REMOTE_DIR/./$p" "$REPO_ROOT/"
done <<< "$present"

if (( ${#dry[@]} == 0 )); then
  {
    echo "# pull receipt $(date -u +%Y-%m-%dT%H:%M:%SZ): size and path of each file on the laptop"
    cd "$REPO_ROOT"
    # shellcheck disable=SC2086
    find $PATHS -type f -printf '%s %p\n' 2>/dev/null
  } | ssh "${SSH_OPTS[@]}" "$SSH_USER@$ip" "cat > '$REMOTE_DIR/policy/lambda/.pull-receipt'" \
    || echo "warning: the pull is good, but the receipt did not reach the instance" >&2
fi
