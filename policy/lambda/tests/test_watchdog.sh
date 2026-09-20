#!/usr/bin/env bash
# watchdog.sh against a local folder in place of the instance (WATCHDOG_SSH_OVERRIDE), a fake
# pull.sh and --terminate-cmd. One case per rule of docs/specs/lambda-training-design.md.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
failed=0

setup() {  # $1: seconds since the launch
  tmp="$(mktemp -d)"
  mkdir -p "$tmp/lambda" "$tmp/remote/policy/lambda"
  cp "$HERE/../watchdog.sh" "$tmp/lambda/"
  printf '#!/usr/bin/env bash\necho pull >> "%s/pulls"\nexit "${FAKE_PULL_RC:-0}"\n' "$tmp" > "$tmp/lambda/pull.sh"
  chmod +x "$tmp/lambda/pull.sh"
  markers="$tmp/remote/policy/lambda"
  touch "$markers/.watchdog-alive"
  printf 'LAMBDA_INSTANCE_ID=i-test\nLAMBDA_INSTANCE_IP=192.0.2.1\nLAMBDA_LAUNCH_EPOCH=%s\nRENTAL_MAX_HOURS=1\n' \
    "$(( $(date +%s) - ${1:-0} ))" > "$tmp/lambda/.rental"
}
# $1: seconds to let it run; the rest: flags. Exit 124 = it was still watching.
watch() {
  local seconds="$1"; shift
  LAMBDA_REMOTE_DIR="$tmp/remote" WATCHDOG_SSH_OVERRIDE="${SSH_OVERRIDE:-bash -c}" timeout "$seconds" \
    "$tmp/lambda/watchdog.sh" --interval 1 --pull-retry-wait 0 --terminate-cmd "echo \$LAMBDA_INSTANCE_ID > '$tmp/terminated'" "$@" \
    > "$tmp/out" 2>&1
}
check() { if eval "$2"; then echo "ok   $1"; else echo "FAIL $1"; cat "$tmp/out"; failed=1; fi; }
pulls() { if [[ -f "$tmp/pulls" ]]; then wc -l < "$tmp/pulls"; else echo 0; fi; }

setup; touch -d '-100 seconds' "$markers/.watchdog-alive"
watch 10 --timeout 50
check "1 alive older than the timeout: final pull, terminate" '[[ -e "$tmp/terminated" && $(pulls) -ge 1 ]]'

setup
watch 4 --timeout 50
check "1 fresh alive: keeps watching" '[[ $? == 124 && ! -e "$tmp/terminated" ]]'

setup; rm "$markers/.watchdog-alive"
watch 4 --timeout 50
check "1 no alive file yet: counts from the first probe" '[[ ! -e "$tmp/terminated" ]]'

setup; touch -d '+1 day' "$markers/.watchdog-alive"
watch 12 --timeout 3
check "1 a future-dated alive is read as now" '[[ -e "$tmp/terminated" ]]'

setup
SSH_OVERRIDE=false watch 10 --unreachable-timeout 2
check "2 unreachable: terminate, PULL-FAILED on the laptop, no pull" \
  '[[ -e "$tmp/terminated" && $(pulls) == 0 ]] && ls "$tmp"/lambda/PULL-FAILED-* >/dev/null'

setup
( sleep 2; touch "$markers/.watchdog-terminate" ) &
watch 12
check "3 terminate marker: final pull, terminate the instance of .rental" '[[ "$(cat "$tmp/terminated" 2>/dev/null)" == i-test && $(pulls) -ge 1 ]]'

setup; touch -d '-1 hour' "$markers/.watchdog-terminate"
watch 4
check "3 a terminate marker older than the first probe is ignored" '[[ ! -e "$tmp/terminated" ]]'

setup $(( 3600 - 600 ))
watch 4
check "4 20 minutes to the cap: the warning file, no terminate" '[[ -e "$markers/.watchdog-cap-warning" && ! -e "$tmp/terminated" ]]'

setup
watch 3
check "4 far from the cap: no warning" '[[ ! -e "$markers/.watchdog-cap-warning" ]]'

setup 3700
watch 10
check "5 a watchdog started after the cap terminates at once" '[[ -e "$tmp/terminated" && $(pulls) -ge 1 ]]'

setup
( sleep 2; touch "$markers/.watchdog-fetch" ) &
watch 5 --pull-interval 1000
check "6 fetch marker: one more pull, the marker is gone" '[[ $(pulls) == 2 && ! -e "$markers/.watchdog-fetch" ]]'

setup
watch 5 --pull-interval 1
check "7 a pull at each pull interval" '[[ $(pulls) -ge 3 ]]'

setup; touch -d '-100 seconds' "$markers/.watchdog-alive"
FAKE_PULL_RC=1 watch 10 --timeout 50
check "a failed final pull: the scheduled pull and three attempts, PULL-FAILED, terminate all the same" \
  '[[ -e "$tmp/terminated" && $(pulls) == 4 ]] && ls "$tmp"/lambda/PULL-FAILED-* >/dev/null'

setup
watch 3 & sleep 1
LAMBDA_REMOTE_DIR="$tmp/remote" WATCHDOG_SSH_OVERRIDE="bash -c" "$tmp/lambda/watchdog.sh" --interval 1 >/dev/null 2>&1; second=$?
wait
check "a second watchdog on one rental refuses to start" '[[ $second != 0 ]]'

exit $failed
