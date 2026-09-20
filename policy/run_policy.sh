#!/usr/bin/env bash
# Runs on the GPU laptop: the policy server and the robot client of the inference loop, one command.
#
#   policy/run_policy.sh      # Ctrl+C stops both
#
# Settings: policy/.env (see .env.example). The ROS side runs first: rosbridge, the two cameras,
# and a HAL that is not passive. README.md, Inference loop.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

# Every dataset has this string, character for character (README.md, The instruction)
TASK="grasp and put down objects, make a peace sign at a person"

[[ -f .env ]] || { echo "error: no policy/.env: copy .env.example and set POLICY_CHECKPOINT" >&2; exit 1; }
set -a
# shellcheck disable=SC1091
source .env
set +a
checkpoint="${POLICY_CHECKPOINT:?is not set (policy/.env)}"
[[ -f "$checkpoint/model.safetensors" ]] || {
  echo "error: no model.safetensors in $checkpoint: POLICY_CHECKPOINT is a pretrained_model folder, absolute or from policy/" >&2
  exit 1
}
python="${PYTHON:-.venv/bin/python}"
port="${POLICY_PORT:-8080}"

"$python" -m lerobot.async_inference.policy_server --port="$port" &
server=$!
trap 'kill "$server" 2>/dev/null; wait "$server" 2>/dev/null || true' EXIT
until (exec 3<>"/dev/tcp/localhost/$port") 2>/dev/null; do
  kill -0 "$server" 2>/dev/null || { echo "error: the policy server stopped before it listened on port $port" >&2; exit 1; }
  sleep 1
done

"$python" -m lerobot.async_inference.robot_client \
  --robot.type=exo_hand --robot.host="${ROS_HOST:-localhost}" --robot.id=exo \
  --server_address="localhost:$port" \
  --policy_type=smolvla --pretrained_name_or_path="$checkpoint" \
  --policy_device="${POLICY_DEVICE:-cuda}" \
  --task="$TASK" \
  --fps="${POLICY_FPS:-30}" --actions_per_chunk="${POLICY_ACTIONS_PER_CHUNK:-20}" --chunk_size_threshold=0.7
