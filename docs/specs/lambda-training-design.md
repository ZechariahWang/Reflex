# Lambda training: rented GPU, local watchdog, agent on the instance

How a SmolVLA fine-tune runs on a rented Lambda Cloud GPU with no person at the
keyboard. Status: design only, nothing implemented. Date: 2026-09-19. This
replaces the manual Lambda steps of `../system-design.md` (Training) and closes
its dataset storage question: the dataset goes from the laptop to the instance
by `rsync` and nowhere else.

The scripts are a stripped copy of the Lambda scripts of the `altrux` project
(`altrux/scripts/lambda_*.sh`), which ran many unattended rentals. The contract
between the laptop and the instance is the same, with one change: the watchdog
reads only files.

## Decisions

- **Platform:** Lambda Cloud, one instance per rental, one person launches. The
  scripts expect exactly one active instance on the account.
- **Model:** SmolVLA with the default freeze (`freeze_vision_encoder=true`,
  `train_expert_only=true`): only the action expert and the state and action
  projections train. The dataset is small, the wrist RGB image is in the
  pretraining distribution (`camera2`), and the new part of the task is the
  action space. π0.5 is rejected: ~3.3B parameters do not fit the 8 GB GPU
  laptop.
- **Agent:** Claude Code (Opus) runs on the instance with the `exo-trainer`
  skill. It is a variant runner: it executes the variants of `plan.md` in
  order, keeps each run healthy, evaluates each checkpoint, applies the stop
  rule of the plan, and writes the run notes. It can skip or reorder a variant
  with a recorded reason. It does not invent variants or change
  hyperparameters that the plan does not name. It never asks a question: a
  question stalls a billed instance.
- **Secrets on the instance:** only `CLAUDE_CODE_OAUTH_TOKEN` (from
  `claude setup-token`), sent in a temporary env file, never on a command line.
  No Lambda API key, no GitHub token, no `HF_TOKEN` (`smolvla_base` is public).
  Revoke the token after the hackathon.
- **Transport:** `rsync` in both directions, no git on the instance. Code that
  the agent changes comes home as a patch file in the run notes folder; a
  person applies and commits it on the laptop.
- **Checkpoints go to the laptop only.** No Hugging Face push.
- **The watchdog runs on the laptop and reads only files.** It has no process
  detection. Liveness is one file that two writers on the instance touch
  (Liveness, below). The laptop must stay awake and online: it is the only
  thing that stops the billing.
- **Hard limit:** `LAMBDA_MAX_HOURS` (default 4), enforced by the watchdog.
  Nothing on the instance can change it.
- **GPU:** one type in `LAMBDA_INSTANCE_TYPE`. If it is sold out, the launch
  polls until capacity appears. A person chooses the type. Do not use GH200
  (ARM: `torchcodec` and FFmpeg wheels are a risk).

## Scope

In: the scripts in `policy/lambda/`, the `exo-trainer` skill, the held-out
evaluation script, the synthetic dataset generator, the plan format and a first
plan, their tests, the two smoke levels, the doc updates.

Out:
- Depth and the forehead camera as inputs. The recorder has one image,
  `camera2`. When it has more, only `plan.md` changes.
- Resume of a run across rentals. A rental starts each variant from
  `smolvla_base`.
- More than one instance, more than one person on one account.
- The inference loop and any test on the hand. The held-out number is a filter
  for which checkpoints deserve a test on the hand, not the verdict.

## Files

```
policy/lambda/
  launch.sh          laptop: provision, wait for ssh, upload, start setup, open tmux
  setup.sh           instance: uv, FFmpeg, lerobot, claude CLI, tmux sessions
  pull.sh            laptop: rsync artifacts down, write the receipt back
  watchdog.sh        laptop: pulls, liveness, cap, terminate
  terminate.sh       laptop: terminate through the API
  check_key.sh       laptop: is LAMBDA_API_KEY valid
  check_instance.sh  laptop: which instance would terminate target
  run_logged.sh      instance: run one long command with log, EXIT= marker, liveness
  tests/             shell tests for watchdog.sh and run_logged.sh
  .env.example
policy/lerobot_robot_exo_hand/
  heldout.py         the seeded split and the held-out evaluation
  synth_dataset.py   a fake dataset in the recorder's format, for the smoke test
.claude/skills/exo-trainer/SKILL.md
docs/notes/training/
  plan.md            a person writes it before a rental
  runs/RUN-<UTC>/    the agent writes it: notes.md, results.jsonl, *.patch
```

`policy/outputs/`, `policy/logs/` and `policy/lambda/.rental` are ignored by git.

Dropped from altrux: Codex support, the wheel harvest, `mem_state.pt`, the
resume checkpoint staging, the data and cache artifact lists, the GH200
settings, the rescue branch, `--arm-after-training` and the `pgrep` pattern.

## Data flow

```
laptop                                         instance (~/htn)
------                                         ----------------
launch.sh --rsync up--> policy/ (no .venv, outputs, .env, other datasets)
                        policy/datasets/<name>
                        .claude/skills/exo-trainer/
                        docs/notes/training/
          --ssh-------> setup.sh (through run_logged.sh) in tmux `train`
                        claude in tmux `experimenter`, jobs in tmux `work`

watchdog.sh --ssh, every 60 s--> reads 4 marker files
            <--rsync, every 5 min and on request--
                        policy/outputs/, policy/logs/, docs/notes/training/runs/
            --writes--> .pull-receipt (what arrived, with sizes)
            --API-----> terminate
```

Before anything bills, `launch.sh` shows a confirm screen: the instance type,
its price from the API, the cap, and every path that goes up with its size. It
refuses to start if `plan.md` is absent, if the dataset folder is absent, or if
an `.env` file is inside the upload set.

After launch, a local tmux session `htn-train` has four windows: `watch` (the
watchdog), `train`, `agent` and `work` (ssh into the remote sessions; each
waits until its session exists). `--no-watch` starts none of this.

## Liveness

All marker files are in `~/htn/policy/lambda/` on the instance.

| File | Writer | Reader | Meaning |
|---|---|---|---|
| `.watchdog-alive` | agent, `run_logged.sh` | watchdog | something makes progress |
| `.watchdog-fetch` | agent | watchdog | pull now; the watchdog deletes it |
| `.watchdog-terminate` | agent | watchdog | the rental is over |
| `.watchdog-cap-warning` | watchdog | agent's Monitor | 20 minutes to the cap |
| `.pull-receipt` | `pull.sh` | agent | UTC time and `size path` of each file as it is on the laptop |

Two writers touch `.watchdog-alive`:

1. **The agent**, at each wake while it works: between variants, during a crash
   diagnosis, during the closing notes.
2. **`run_logged.sh <name> <command...>`**, the only way a long command starts
   (setup, `lerobot-train`, the evaluation, the generator). It runs the command
   as `2>&1 | tee policy/logs/<name>.log`, appends `EXIT=<code>` to the log at
   the end, and touches `.watchdog-alive` every 60 s **while the log grows**.
   When the log has not changed for `STALE_SECONDS` (default 1200) it stops the
   touches, so a hang reads as dead. It does not kill the command.

Watchdog rules, one probe every 60 s:

| # | Condition | Action |
|---|---|---|
| 1 | `.watchdog-alive` older than `--timeout` (1800 s) | final pull, terminate |
| 2 | ssh fails for `--unreachable-timeout` (900 s) while the API says active | terminate, write `PULL-FAILED-<UTC>` on the laptop |
| 3 | `.watchdog-terminate` exists and is newer than the first good probe | final pull, terminate |
| 4 | time since launch >= cap - 20 min | write `.watchdog-cap-warning` once |
| 5 | time since launch >= cap | final pull, terminate |
| 6 | `.watchdog-fetch` exists | pull, delete the marker |
| 7 | `--pull-interval` (300 s) since the last pull | pull |

`launch.sh` touches `.watchdog-alive` once after the upload, so rule 1 counts
from a known time. A future-dated mtime is read as now. The final pull has a
time limit and two retries; the terminate happens whether it succeeds or not.
`launch.sh` writes the launch time and the instance id to `policy/lambda/.rental`
(ignored by git), so a restarted watchdog keeps the same cap.
`--terminate-cmd "echo"` runs the watchdog with no real terminate.

Results:

| Situation | Outcome |
|---|---|
| Healthy training, dead agent (rate limit, outage, full context) | the variant finishes, the pulls bring it home, terminate 30 min later |
| Hung training, dead agent | terminate ~50 min after the hang starts |
| Agent works, nothing trains | the agent's touches keep the instance |
| `--smoke-scripts` (no agent) | the wrapper is the writer |
| Laptop asleep or offline | **nothing stops the billing** |

The marker files are a guardrail against a forgotten instance, not a security
boundary: a process on the instance can touch `.watchdog-alive` with no end.
The cap is the boundary.

## Held-out evaluation

`lerobot-train` has no validation split, and the training loss cannot compare
variants. `heldout.py` has two functions and one command:

- `split(num_episodes, fraction=0.1, seed=0)` returns disjoint `train` and
  `heldout` episode lists, at least one held-out episode, the same lists for
  the same inputs. `python -m lerobot_robot_exo_hand.heldout split` prints
  both lists. It runs once per rental on the instance (the agent, or the
  scripted runner of `--smoke-scripts`), and the lists go into the run notes.
  Every variant of a rental trains with `--dataset.episodes=<train list>`.
- The command loads one checkpoint, runs it on the held-out frames in batches
  with a fixed seed, and compares the first action of each predicted chunk with
  the recorded action. It appends one JSON line to `results.jsonl`: variant,
  step, mean absolute error overall and per finger, and the error on the frames
  within 0.5 s of a close or a release (a recorded action that crosses 0.5).
  `--stride N` takes every Nth frame.

The measure is the action error, not the flow-matching loss: that loss has a
random timestep and random noise, so it moves between two runs of one
checkpoint. The error is on the `0 .. 1` command scale.

The evaluation runs in the `work` session while the next steps train (a default
fine-tune uses 10-24 GB). If the training batch already fills the VRAM, the
agent evaluates between variants.

## Plan format

`docs/notes/training/plan.md` is prose for people plus one fenced `yaml` block
that the agent reads:

```yaml
dataset: exo_grasp            # folder in policy/datasets/
task: "<the constant instruction of the dataset>"
heldout: {fraction: 0.1, seed: 0}
stop_rule: "held-out error rises at two consecutive checkpoints: stop, keep the best"
common: "--policy.path=lerobot/smolvla_base --policy.device=cuda --policy.push_to_hub=false --batch_size=64 --save_freq=1000 --wandb.enable=false"
variants:
  - {name: default,     args: "--steps=5000"}
  - {name: short_chunk, args: "--steps=5000 --policy.chunk_size=20 --policy.n_action_steps=20"}
  - {name: train_vlm,   args: "--steps=5000 --policy.train_expert_only=false", optional: true}
  - {name: unfrozen,    args: "--steps=5000 --policy.freeze_vision_encoder=false --policy.train_expert_only=false", optional: true}
```

The agent runs the variants in order and runs an `optional` one only if the
time to the cap permits it. Each variant writes to
`policy/outputs/train/<run>/<name>`. The spec fixes the format; the list is a
person's choice for each rental.

## The skill

`exo-trainer` is `altrux-experimenter` cut down to this job. It keeps:

- never ask a question; every decision goes into the notes with its reason;
- training runs in tmux `train`, all other jobs in named windows of tmux
  `work`, always through `run_logged.sh`, never inline;
- one persistent Monitor for the whole session, armed first. It wakes the agent
  on: a new `EXIT=` line in a log, an error signature (`Traceback`,
  `out of memory`, `Killed`, `nan`), a new `checkpoints/<step>` folder (new),
  `.watchdog-cap-warning` (new), and a heartbeat (300 s for the first hour
  after a training start, then 900 s) that carries the last log line and the
  log's idle time;
- verbatim commands in the notes at the moment they run; GPU use and VRAM
  recorded once per variant when it is steady;
- a crash gets a diagnosis and one bounded retry (out of memory: halve the
  batch and record it); the same failure twice ends the variant;
- the shutdown checklist: verify the last checkpoint, write the closing notes
  with the comparison table and the best checkpoint of each variant, touch
  `.watchdog-fetch`, wait for a fresh `.pull-receipt`, check that each
  checkpoint, `results.jsonl` and the notes are in it at a plausible size, then
  touch `.watchdog-terminate` as the last action;
- no Lambda credentials, and no attempt to get any.

It drops the open experiment loop, the data sanity gate, git, and the rescue
branch. On the cap warning the agent stops training, evaluates the newest
checkpoint, and runs the shutdown checklist.

`setup.sh` starts the agent as
`claude --model opus --dangerously-skip-permissions` in tmux `experimenter`
with `/exo-trainer` as the first prompt. The instance is disposable and holds
one secret, so skipped prompts are acceptable there. Before that, `setup.sh`
checks that the token gives an Opus answer and fails with a clear message if
not.

## Smoke test

Both levels use `synth_dataset.py`: a few short episodes of noise images and
sine-wave fingers in the format that `lerobot-record` writes with `ExoHand`.
The held-out number of such data has no meaning; the smoke test checks that a
number appears.

| Level | Command | Proves |
|---|---|---|
| Scripts | `launch.sh --smoke-scripts` | launch, upload, setup, 50 training steps, one evaluation, pull with receipt, liveness by the wrapper, terminate. No agent. About 10 minutes on the cheapest type. |
| Agent | `launch.sh --smoke` | the same with the agent and a plan of two 50-step variants: the skill, the Monitor, the checkpoint wake, the shutdown checklist. |

Success criterion for each: a `pretrained_model` folder and a `results.jsonl`
on the laptop, a receipt that lists them, and no active instance at the end.
The cap for a smoke run is 1 hour.

## Tests

- `pytest`: `split` is seeded, disjoint, complete and never empty; the error
  math on a fake policy with a known output; the close and release window; the
  generator's features equal `ExoHand`'s `observation_features` and
  `action_features`, so a format drift fails a test and not a rental.
- Shell tests with a fake `ssh` and `--terminate-cmd echo` for `watchdog.sh`:
  each of the 7 rules, the stale `.watchdog-terminate`, a future-dated
  `.watchdog-alive`, the cap after a watchdog restart, a failed final pull
  still terminates. For `run_logged.sh`: the `EXIT=` line on success and on
  failure, touches while the log grows, no touches when it is stale.
- `launch.sh`, `setup.sh` and `pull.sh` are proven by the smoke levels only.

## Risks

- **The laptop is a single point of failure for billing.** Accepted; the cap
  bounds a rental to `LAMBDA_MAX_HOURS` only while the watchdog runs.
- **A subscription rate limit stops the agent.** The run in progress finishes
  and comes home; the later variants do not run.
- **Whether the OAuth token permits Opus is not verified.** `setup.sh` checks
  it in the first minutes.
- **`lerobot-train` option names for the variants (`chunk_size`,
  `n_action_steps`, `train_expert_only`) are not run yet.** The agent smoke
  level uses the same option names, so a wrong name fails there.
- **The synthetic dataset can pass where the real one fails** (video codec,
  episode count, image size). The feature test reduces this; the first real
  rental is still the first real test.

## Doc updates with the implementation

- Root `CLAUDE.md`: the layout rule permits `.claude/`; `policy/` names
  `policy/lambda/`; `docs/notes/training/` holds the training plan and the run
  notes.
- `policy/README.md` and `../system-design.md`: the Training sections point
  here; the dataset storage question is closed.
- `../notes/next-work.md`: the state of this work.
