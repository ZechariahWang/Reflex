#!/usr/bin/env bash
# Runs ON the instance. The only way a long command starts there:
#
#   policy/lambda/run_logged.sh <name> <command...>
#
# The pane shows the output and policy/logs/<name>.log keeps it. `EXIT=<code>` is the last line
# of the log: the agent's Monitor wakes on it. While the log grows, .watchdog-alive is touched
# every TOUCH_INTERVAL seconds; a log that is silent for STALE_SECONDS gets no more touches, so
# the watchdog on the laptop reads a hang as dead. The command is never killed from here.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
name="${1:?usage: run_logged.sh <name> <command...>}"; shift
log="$DIR/../logs/$name.log"
alive="$DIR/.watchdog-alive"
stale="${STALE_SECONDS:-1200}"
interval="${TOUCH_INTERVAL:-60}"

mkdir -p "$(dirname "$log")"
touch "$log" "$alive"
(
  while sleep "$interval"; do
    (( $(date +%s) - $(stat -c %Y "$log") < stale )) && touch "$alive"
  done
) &
toucher=$!
trap 'kill "$toucher" 2>/dev/null' EXIT

"$@" 2>&1 | tee -a "$log"
code="${PIPESTATUS[0]}"
echo "EXIT=$code" | tee -a "$log"
exit "$code"
