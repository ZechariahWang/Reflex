#!/usr/bin/env bash
# Shell into the sim container (Docker Desktop on Windows / mac; native Linux
# devs use distrobox, see ../CLAUDE.md). Builds the image on first use. The
# repo is mounted at /ws/htn-2026; the console ports come through to the host.
#
#   physical_layer/docker/run.sh        # interactive shell
#   physical_layer/docker/run.sh -d     # keep one running in the background, then `docker exec -it htn-sim bash`
#
# Inside:  physical_layer/build.sh && ros2 launch htn_launch sim.launch.py camera:=none
#          application/dev.sh   (second shell)  ->  http://localhost:3000 on the host
set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
docker image inspect htn-sim >/dev/null 2>&1 || docker build -t htn-sim "$ROOT/physical_layer/docker"

HOST_ROOT="$ROOT"
if command -v cygpath >/dev/null 2>&1; then
  HOST_ROOT="$(cygpath -w "$ROOT")"   # Git Bash: docker wants C:\..., not /c/...
  export MSYS_NO_PATHCONV=1           # and must not rewrite the /ws/... container paths
fi

mode=()
if [[ "${1:-}" == "-d" ]]; then
  shift
  mode=(-d)
  set -- sleep infinity
elif [[ -t 0 ]]; then
  mode=(-it)
fi

# Mount points for the named volumes (a Windows bind mount is too slow for build output)
for d in physical_layer/ros2_ws/build physical_layer/ros2_ws/install physical_layer/ros2_ws/log \
         application/frontend/node_modules application/backend/.venv; do
  mkdir -p "$ROOT/$d"
done

exec docker run --rm "${mode[@]}" --name htn-sim \
  --mount "type=bind,src=$HOST_ROOT,dst=/ws/htn-2026" \
  -v htn-build:/ws/htn-2026/physical_layer/ros2_ws/build \
  -v htn-install:/ws/htn-2026/physical_layer/ros2_ws/install \
  -v htn-log:/ws/htn-2026/physical_layer/ros2_ws/log \
  -v htn-node-modules:/ws/htn-2026/application/frontend/node_modules \
  -v htn-venv:/ws/htn-2026/application/backend/.venv \
  -p 3000:3000 -p 8000:8000 -p 9090:9090 -p 8765:8765 \
  -e BACKEND_HOST=0.0.0.0 \
  -e DISPLAY=:0 -v /mnt/wslg/.X11-unix:/tmp/.X11-unix \
  htn-sim "$@"
