#!/usr/bin/env bash
# Terminates the rented instance through the API: the only thing that stops the billing.
# The instance is LAMBDA_INSTANCE_ID (the watchdog passes it, launch.sh writes it to .rental);
# with neither, the one instance of the account. check_instance.sh shows the target.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
require LAMBDA_API_KEY

instance_id="${LAMBDA_INSTANCE_ID:-}"
if [[ -z "$instance_id" ]]; then
  list="$(instances)"
  [[ "$(grep -c . <<< "$list")" == 1 ]] || { echo "error: no .rental and not exactly one instance; set LAMBDA_INSTANCE_ID:" >&2; echo "$list" >&2; exit 1; }
  instance_id="${list%% *}"
fi

echo "Terminating instance $instance_id..."
api instance-operations/terminate -H "Content-Type: application/json" -d "{\"instance_ids\":[\"$instance_id\"]}"
echo
rm -f "$SCRIPT_DIR/.rental"
echo "Terminate request sent. Check: policy/lambda/check_instance.sh"
