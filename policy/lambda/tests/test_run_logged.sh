#!/usr/bin/env bash
# run_logged.sh: the EXIT= line, and the liveness touches only while the log grows.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
failed=0

setup() {  # a copy, so logs/ and .watchdog-alive land in a temporary folder
  tmp="$(mktemp -d)"
  mkdir -p "$tmp/policy/lambda"
  cp "$HERE/../run_logged.sh" "$tmp/policy/lambda/"
  run="$tmp/policy/lambda/run_logged.sh"
  alive="$tmp/policy/lambda/.watchdog-alive"
}
check() { if eval "$2"; then echo "ok   $1"; else echo "FAIL $1"; failed=1; fi; }

setup
"$run" good bash -c 'echo hello; echo problem >&2' >/dev/null; code=$?
check "success: exit code 0, both streams and EXIT=0 in the log" \
  '[[ $code == 0 ]] && grep -q hello "$tmp/policy/logs/good.log" && grep -q problem "$tmp/policy/logs/good.log" && [[ "$(tail -1 "$tmp/policy/logs/good.log")" == EXIT=0 ]]'
check "the start is a sign of life" '[[ -e "$alive" ]]'

"$run" bad bash -c 'exit 3' >/dev/null; code=$?
check "failure: the exit code of the command, and EXIT=3 in the log" \
  '[[ $code == 3 && "$(tail -1 "$tmp/policy/logs/bad.log")" == EXIT=3 ]]'

setup
TOUCH_INTERVAL=1 STALE_SECONDS=3 "$run" grows bash -c "sleep 0.5; rm -f '$alive'; for i in 1 2 3; do echo \$i; sleep 1; done; test -e '$alive'" >/dev/null
check "a growing log: .watchdog-alive is touched again" '[[ $? == 0 ]]'

setup
TOUCH_INTERVAL=1 STALE_SECONDS=2 "$run" hangs bash -c "echo start; sleep 3.5; rm -f '$alive'; sleep 2.5; ! test -e '$alive'" >/dev/null
check "a silent log: no touch after STALE_SECONDS, the command still runs" '[[ $? == 0 ]]'

exit $failed
