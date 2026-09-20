#!/usr/bin/env bash
# Runs ON the instance, started by launch.sh through run_logged.sh in the tmux session `train`:
# the Python environment, then the agent (or, for --smoke-scripts, a fixed run with no agent).
# It holds no Lambda key and needs none. The only secret is CLAUDE_CODE_OAUTH_TOKEN, from the
# environment; nothing here prints it.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$DIR/../.." && pwd)"
# shellcheck disable=SC1091
source "$DIR/rental.env"
step() { printf '\n=== %s ===\n' "$1"; }

# The scripts smoke level has no agent: whatever fails, it asks for the pull and the terminate
if [[ "$MODE" == smoke-scripts ]]; then
  finish() {
    step "Fetch, check the receipt, terminate"
    touch "$DIR/.watchdog-fetch"
    for _ in $(seq 1 60); do
      [[ "$DIR/.pull-receipt" -nt "$DIR/.watchdog-fetch" ]] && break
      sleep 10
    done
    grep -E 'pretrained_model/model.safetensors|results.jsonl' "$DIR/.pull-receipt" || echo "SMOKE FAILED: no checkpoint or no results.jsonl in the receipt"
    touch "$DIR/.watchdog-terminate"
  }
  trap finish EXIT
fi

step "Python environment (uv, FFmpeg, lerobot)"
# The untouched code: the agent makes its patch files with `diff -ru` against this copy
mkdir -p ~/pristine && cp -a "$REPO/policy/lerobot_robot_exo_hand" "$REPO/policy/lambda" ~/pristine/
command -v uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh
# shellcheck disable=SC1091
[[ -f "$HOME/.local/bin/env" ]] && . "$HOME/.local/bin/env"
# torchcodec decodes the dataset video with the FFmpeg libraries; without them lerobot uses the slower pyav
command -v ffmpeg >/dev/null 2>&1 || sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ffmpeg
cd "$REPO/policy"
uv venv --python 3.12 --allow-existing
# auto: the torch build for the CUDA version of this driver. The default wheel is for a newer
# CUDA than the driver of a Lambda image has, and torch then sees no GPU.
uv pip install --python .venv/bin/python --torch-backend=auto --reinstall-package torch --reinstall-package torchvision \
  -e . "lerobot[smolvla,training]==0.6.1"
.venv/bin/python -c "import torch, sys; ok = torch.cuda.is_available(); print('torch', torch.__version__, 'cuda', ok); sys.exit(0 if ok else 1)" \
  || { echo "error: torch sees no CUDA GPU" >&2; exit 1; }

if [[ "$MODE" != full ]]; then
  step "Fake dataset"
  .venv/bin/python -m lerobot_robot_exo_hand.synth_dataset --out "datasets/$DATASET" --force
fi

# The scripts smoke level: what the agent does, as a fixed list, with the wrapper as the only
# writer of .watchdog-alive. Whatever fails, it asks for the pull and the terminate.
if [[ "$MODE" == smoke-scripts ]]; then
  run="RUN-$(date -u +%Y%m%dT%H%M%SZ)"
  notes="$REPO/docs/notes/training/runs/$run"
  mkdir -p "$notes"
  step "Split, 50 training steps, one evaluation"
  .venv/bin/python -m lerobot_robot_exo_hand.heldout split --root "datasets/$DATASET" | tee "$notes/notes.md"
  train="$(sed -n 's/^train=//p' "$notes/notes.md")"
  "$DIR/run_logged.sh" smoke-train .venv/bin/lerobot-train --policy.path=lerobot/smolvla_base --policy.device=cuda \
    --policy.push_to_hub=false --dataset.repo_id="local/$DATASET" --dataset.root="datasets/$DATASET" \
    "--dataset.episodes=$train" --batch_size=8 --steps=50 --save_freq=50 --wandb.enable=false \
    --output_dir="outputs/train/$run/smoke"
  "$DIR/run_logged.sh" smoke-eval .venv/bin/python -m lerobot_robot_exo_hand.heldout eval --root "datasets/$DATASET" \
    --checkpoint "outputs/train/$run/smoke/checkpoints/last/pretrained_model" --variant smoke --out "$notes/results.jsonl"
  exit 0
fi

step "Claude Code"
command -v claude >/dev/null 2>&1 || curl -fsSL https://claude.ai/install.sh | bash
export PATH="$HOME/.local/bin:$PATH"
[[ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]] || { echo "error: no CLAUDE_CODE_OAUTH_TOKEN reached the instance" >&2; exit 1; }
# The first-run prompts (onboarding, folder trust, the skip-permissions confirm) would block a session with no person
REPO="$REPO" python3 - <<'PY'
import json, os, pathlib
home = pathlib.Path.home()
settings = home / ".claude/settings.json"
s = json.loads(settings.read_text()) if settings.exists() else {}
s.setdefault("theme", "dark")
s["skipDangerousModePermissionPrompt"] = True
settings.parent.mkdir(exist_ok=True)
settings.write_text(json.dumps(s, indent=2) + "\n")
state = home / ".claude.json"
d = json.loads(state.read_text()) if state.exists() else {}
d["hasCompletedOnboarding"] = True
d.setdefault("projects", {}).setdefault(os.environ["REPO"], {})["hasTrustDialogAccepted"] = True
state.write_text(json.dumps(d, indent=2) + "\n")
PY
answer="$(cd "$REPO" && claude --model opus -p "Reply with the one word: ready" --output-format json)" || {
  echo "error: the token gives no Opus answer (rate limit, plan with no Opus, or a revoked token). No agent starts, and the watchdog terminates the instance in 30 min." >&2
  exit 1
}
grep -qi opus <<< "$answer" || echo "warning: the answer does not name an Opus model; read it: ${answer:0:400}" >&2

step "The agent, in tmux 'experimenter'"
tmux has-session -t work 2>/dev/null || tmux new-session -d -s work -c "$REPO"
# A tmux pane is a child of the tmux server: it gets the token and the PATH only if they are passed
tmux new-session -d -s experimenter -c "$REPO" -e CLAUDE_CODE_OAUTH_TOKEN="$CLAUDE_CODE_OAUTH_TOKEN" -e PATH="$PATH" \
  "claude --model opus --dangerously-skip-permissions '/exo-trainer You were started by setup.sh on a new instance. Nobody is at the keyboard.'"
echo "Setup complete. The agent runs in tmux 'experimenter'; this session ('train') is for the training."
