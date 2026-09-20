#!/usr/bin/env bash
# Which instance would terminate.sh terminate? Terminates nothing.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
require LAMBDA_API_KEY

list="$(instances)" || { echo "error: GET /instances failed - run check_key.sh" >&2; exit 1; }
echo "Instances that bill on this account:"
echo "${list:-  (none)}" | sed 's/^/  /'
if [[ -n "${LAMBDA_INSTANCE_ID:-}" ]]; then
  echo "terminate.sh would terminate $LAMBDA_INSTANCE_ID (from .rental or the environment)."
  grep -q "^$LAMBDA_INSTANCE_ID " <<< "$list" || { echo "It is NOT in the list above: that rental is over. Delete policy/lambda/.rental." >&2; exit 1; }
elif [[ "$(grep -c . <<< "$list")" == 1 ]]; then
  echo "No .rental: terminate.sh would terminate the one instance above."
else
  echo "No .rental and not exactly one instance: terminate.sh would refuse." >&2
  exit 1
fi
