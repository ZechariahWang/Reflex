#!/usr/bin/env bash
# run_policy.sh: the checkpoint check, the arguments of the client, and no server left behind.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
failed=0
check() { if eval "$2"; then echo "ok   $1"; else echo "FAIL $1"; failed=1; fi; }

setup() {  # a copy with a fake python: the server listens on the port, the client writes its arguments
  tmp="$(mktemp -d)"
  cp "$HERE/../run_policy.sh" "$tmp/"
  mkdir -p "$tmp/ckpt"
  cat > "$tmp/python" <<EOF
#!/usr/bin/env bash
if [[ "\$*" == *policy_server* ]]; then
  echo \$\$ > "$tmp/server.pid"
  exec python3 -c "import socket, time; s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(('localhost', \$POLICY_PORT)); s.listen(); time.sleep(60)"
fi
echo "\$*" > "$tmp/client.args"
EOF
  chmod +x "$tmp/python"
  printf 'POLICY_CHECKPOINT=ckpt\nROS_HOST=10.0.0.7\nPOLICY_PORT=%s\n' $((20000 + RANDOM % 20000)) > "$tmp/.env"
}

setup
PYTHON="$tmp/python" "$tmp/run_policy.sh" >/dev/null 2>&1; code=$?
check "no model.safetensors in the checkpoint: an error, and no server starts" '[[ $code != 0 && ! -e "$tmp/server.pid" ]]'

touch "$tmp/ckpt/model.safetensors"
PYTHON="$tmp/python" "$tmp/run_policy.sh" >/dev/null 2>&1; code=$?
check "the client gets the checkpoint, the host and 30 fps" \
  '[[ $code == 0 ]] && grep -q -- "--pretrained_name_or_path=ckpt" "$tmp/client.args" && grep -q -- "--robot.host=10.0.0.7" "$tmp/client.args" && grep -q -- "--fps=30" "$tmp/client.args"'
check "the console's switch gates the client" 'grep -q -- "--robot.enable_topic=/policy/enabled" "$tmp/client.args"'
check "the server stops with the client" '! kill -0 "$(cat "$tmp/server.pid")" 2>/dev/null'

echo POLICY_GATE=0 >> "$tmp/.env"
PYTHON="$tmp/python" "$tmp/run_policy.sh" >/dev/null 2>&1
check "POLICY_GATE=0: no switch" '! grep -q enable_topic "$tmp/client.args"'

rm "$tmp/.env"
PYTHON="$tmp/python" "$tmp/run_policy.sh" >/dev/null 2>&1
check "no .env: an error" '[[ $? != 0 ]]'

exit $failed
