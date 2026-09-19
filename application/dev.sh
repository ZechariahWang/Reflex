#!/usr/bin/env bash
# Start the simulator console: FastAPI backend (:8000) + Next.js frontend (:3000).
#   ./dev.sh            live, reads ROS through rosbridge on :9090
#   MOCK=1 ./dev.sh     no ROS needed, everything synthesized
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8000}"
# 0.0.0.0 to reach the API from another machine or from outside a container
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
export MOCK="${MOCK:-0}"
export CORS_ORIGINS="${CORS_ORIGINS:-http://localhost:$FRONTEND_PORT,http://127.0.0.1:$FRONTEND_PORT}"
export NEXT_PUBLIC_BACKEND_URL="${NEXT_PUBLIC_BACKEND_URL:-http://localhost:$BACKEND_PORT}"

for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
  if ss -ltnH "sport = :$port" | grep -q .; then
    echo "dev.sh: port $port is already in use" >&2
    exit 1
  fi
done

if [[ ! -x "$ROOT/backend/.venv/bin/python" ]]; then
  echo "dev.sh: creating backend/.venv"
  python3 -m venv "$ROOT/backend/.venv"
fi
# Reinstall whenever requirements.txt is newer than the last install (e.g. after a git pull).
stamp="$ROOT/backend/.venv/.requirements-installed"
if [[ ! -f "$stamp" || "$ROOT/backend/requirements.txt" -nt "$stamp" ]]; then
  echo "dev.sh: installing backend requirements"
  "$ROOT/backend/.venv/bin/pip" install --quiet -r "$ROOT/backend/requirements.txt"
  touch "$stamp"
fi
if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
  echo "dev.sh: installing frontend/node_modules"
  (cd "$ROOT/frontend" && npm ci --no-audit --no-fund)
fi

pids=()
# setsid makes each service the leader of its own process group, so one signal stops its whole tree.
run() { # <label> <dir> <command...>
  local label="$1" dir="$2"
  shift 2
  (cd "$dir" && exec setsid "$@") > >(sed -u "s/^/[$label] /") 2>&1 &
  pids+=("$!")
}

stop() {
  trap - INT TERM EXIT
  echo
  echo "dev.sh: stopping"
  for pid in "${pids[@]}"; do
    kill -TERM -- "-$pid" 2>/dev/null || true
  done
  wait
}
trap stop INT TERM EXIT

run backend "$ROOT/backend" .venv/bin/uvicorn app.main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT"
run frontend "$ROOT/frontend" npx next dev --port "$FRONTEND_PORT"

mode="live, rosbridge ws://${ROSBRIDGE_HOST:-localhost}:${ROSBRIDGE_PORT:-9090}"
[[ "$MOCK" == "1" ]] && mode="mock, no ROS"
echo "dev.sh: console at http://localhost:$FRONTEND_PORT  ($mode)  -  Ctrl-C stops both"

wait -n "${pids[@]}" || true
