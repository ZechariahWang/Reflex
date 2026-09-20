# Sourced by the laptop scripts: the settings, the rental and the two API helpers.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
API="https://cloud.lambdalabs.com/api/v1"
for f in "$SCRIPT_DIR/.env" "$SCRIPT_DIR/.rental"; do
  if [[ -f "$f" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$f"
    set +a
  fi
done
SSH_USER="${LAMBDA_SSH_USER:-ubuntu}"
SSH_KEY_PATH="${LAMBDA_SSH_KEY_PATH:-}"
REMOTE_DIR="${LAMBDA_REMOTE_DIR:-htn}"
# BatchMode: a prompt would hang an unattended pull
SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -o BatchMode=yes -i "$SSH_KEY_PATH")

require() { [[ -n "${!1:-}" ]] || { echo "error: $1 is not set (policy/lambda/.env, see .env.example)" >&2; exit 1; }; }
api() { curl -sf --max-time 30 -u "${LAMBDA_API_KEY}:" "$API/$1" "${@:2}"; }
# stdout: "<id> <ip> <status> <type>" of each instance that bills
instances() {
  api instances | python3 -c "
import json, sys
for i in json.load(sys.stdin).get('data', []):
    if i.get('status') != 'terminated':
        print(i['id'], i.get('ip') or '-', i.get('status'), i.get('instance_type', {}).get('name'))
"
}
