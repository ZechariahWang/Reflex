#!/usr/bin/env bash
# Is LAMBDA_API_KEY of policy/lambda/.env valid? The API has no endpoint for that question, so
# this reads /instance-types, which needs the key and no instance.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
require LAMBDA_API_KEY

status="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 -u "${LAMBDA_API_KEY}:" "$API/instance-types")"
case "$status" in
  200) echo "LAMBDA_API_KEY is valid." ;;
  401|403) echo "LAMBDA_API_KEY is not accepted (HTTP $status)." >&2; exit 1 ;;
  *) echo "error: HTTP $status from the Lambda API" >&2; exit 1 ;;
esac
