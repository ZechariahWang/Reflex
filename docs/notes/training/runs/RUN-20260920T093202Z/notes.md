# RUN-20260920T093202Z

First rental on real data. Goal (from the plan): does the default fine-tune learn the close and
the release at all, and does a shorter action chunk help.

## Rental

Cap: LAUNCH_UTC + MAX_HOURS = 2026-09-20T09:25:33Z + 4h = **2026-09-20T13:25:33Z**.
Shutdown checklist starts by 12:55Z at the latest.

```
MODE=full
DATASET=exo_grasp
INSTANCE_TYPE=gpu_1x_a100_sxm4
MAX_HOURS=4
LAUNCH_UTC=2026-09-20T09:25:33Z
```

GPU: `nvidia-smi -L`

```
GPU 0: NVIDIA A100-SXM4-40GB (UUID: GPU-beb621fa-6302-2d46-72eb-bfffb1a47d45)
```

## Plan block used

```yaml
heldout: {fraction: 0.1, seed: 0}
stop_rule: "held-out error rises at two consecutive checkpoints: stop, keep the best"
common: "--policy.path=lerobot/smolvla_base --policy.device=cuda --policy.push_to_hub=false --batch_size=64 --save_freq=1000 --wandb.enable=false"
variants:
  - {name: default,     args: "--steps=5000"}
  - {name: short_chunk, args: "--steps=5000 --policy.chunk_size=20 --policy.n_action_steps=20"}
  - {name: train_vlm,   args: "--steps=5000 --policy.train_expert_only=false", optional: true}
  - {name: unfrozen,    args: "--steps=5000 --policy.freeze_vision_encoder=false --policy.train_expert_only=false", optional: true}
```

## Split

Made once for the whole rental, fraction 0.1, seed 0. Every variant trains with the same train
list, so the held-out numbers compare within this rental only (not with another rental or
dataset).

Command, as run:

```
.venv/bin/python -m lerobot_robot_exo_hand.heldout split --root datasets/exo_grasp --fraction 0.1 --seed 0
```

train=[0,1,3,4,5,6,7,8,9,10,11,12,13,14,15,17,18,19,20,21,22,23,25,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47]
heldout=[2,16,24,26,48]

44 train episodes, 5 held out.

## Log

- 09:25:33Z instance launched.
- 09:32Z agent started, Monitor armed, split made.
- 09:34Z **Change of plan from the person** (typed at the keyboard, verbatim): "the rental must
  end 90 minutes after the launch. Run only the `default` variant, no other variant. Let it
  train; stop it after the last checkpoint that you can evaluate before the 90-minute mark.
  Then do the normal end-of-rental steps (check the checkpoints, the notes, the fetch and the
  receipt, terminate)."
  New end: 09:25:33Z + 90 min = **10:55:33Z**. Variants `short_chunk`, `train_vlm`, `unfrozen`
  are skipped for this reason. Budget: the training stops early enough that the last
  evaluation and the fetch/receipt finish before 10:55Z; the fetch of ~1 GB per checkpoint
  needs some minutes, so the plan is to stop the training by ~10:25Z at the latest, evaluate,
  then run the shutdown checklist. The laptop's own cap (MAX_HOURS=4) is unchanged from here.

## Variant `default`

Started 09:32:57Z in tmux `train`. Command, exactly as run:

```
cd ~/htn/policy && lambda/run_logged.sh default .venv/bin/lerobot-train --policy.path=lerobot/smolvla_base --policy.device=cuda --policy.push_to_hub=false --batch_size=64 --save_freq=1000 --wandb.enable=false --steps=5000 --dataset.repo_id=local/exo_grasp --dataset.root=datasets/exo_grasp --dataset.episodes=[0,1,3,4,5,6,7,8,9,10,11,12,13,14,15,17,18,19,20,21,22,23,25,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47] --output_dir=outputs/train/RUN-20260920T093202Z/default
```

Steady state at 09:33:31Z: ~1.8 step/s (≈9.3 min per 1000 steps, 5000 steps ≈ 46 min).
`nvidia-smi`: GPU 88 %, VRAM 15647 / 40960 MiB.
Expected checkpoints: 1000 ≈09:42Z, 2000 ≈09:52Z, 3000 ≈10:01Z, 4000 ≈10:11Z, 5000 ≈10:20Z.
Evaluations run in tmux `work` as each checkpoint lands; the stop rule of the plan applies.

### Checkpoint 001000

Written 09:41:53Z, `model.safetensors` 906712520 bytes. Evaluation started 09:42Z in tmux
`work` window `eval-default-001000`, command exactly as run:

```
cd ~/htn/policy && lambda/run_logged.sh eval-default-001000 .venv/bin/python -m lerobot_robot_exo_hand.heldout eval --root datasets/exo_grasp --fraction 0.1 --seed 0 --variant default --checkpoint outputs/train/RUN-20260920T093202Z/default/checkpoints/001000/pretrained_model --out ../docs/notes/training/runs/RUN-20260920T093202Z/results.jsonl 
```
Result (EXIT=0, evaluation took ~184 s, well under the ~9 min between checkpoints, so no
`--stride`): **mae 0.0192**, **mae_near_crossing 0.0666**; per finger thumb 0.0245, index
0.0157, middle 0.0148, ring 0.0193, pinky 0.0216; 3437 held-out frames, 168 near a crossing.

### Checkpoint 002000

Written 09:51:17Z, `model.safetensors` 906712520 bytes. Evaluation started 09:51Z in tmux
`work` window `eval-default-002000`, command exactly as run:

```
cd ~/htn/policy && lambda/run_logged.sh eval-default-002000 .venv/bin/python -m lerobot_robot_exo_hand.heldout eval --root datasets/exo_grasp --fraction 0.1 --seed 0 --variant default --checkpoint outputs/train/RUN-20260920T093202Z/default/checkpoints/002000/pretrained_model --out ../docs/notes/training/runs/RUN-20260920T093202Z/results.jsonl 
```
Result (EXIT=0, ended 09:54:47Z): **mae 0.0170**, **mae_near_crossing 0.0639**; per finger thumb
0.0207, index 0.0147, middle 0.0136, ring 0.0173, pinky 0.0187. Both numbers improved on
step 1000 (0.0192 / 0.0666): stop rule not triggered, training continues.

### Checkpoint 003000

Written 10:00:39Z, `model.safetensors` 906712520 bytes. Evaluation started 10:00Z in tmux
`work` window `eval-default-003000`, command exactly as run:

```
cd ~/htn/policy && lambda/run_logged.sh eval-default-003000 .venv/bin/python -m lerobot_robot_exo_hand.heldout eval --root datasets/exo_grasp --fraction 0.1 --seed 0 --variant default --checkpoint outputs/train/RUN-20260920T093202Z/default/checkpoints/003000/pretrained_model --out ../docs/notes/training/runs/RUN-20260920T093202Z/results.jsonl 
```
Result (EXIT=0, ended 10:03:56Z): **mae 0.0149**, **mae_near_crossing 0.0634**; per finger thumb
0.0184, index 0.0125, middle 0.0118, ring 0.0141, pinky 0.0179. Both numbers improved on
step 2000 (0.0170 / 0.0639); the crossing number is flattening. Stop rule not triggered.

### Checkpoint 004000

Written 10:10:00Z, `model.safetensors` 906712520 bytes. Evaluation started 10:10Z in tmux
`work` window `eval-default-004000`, command exactly as run:

```
cd ~/htn/policy && lambda/run_logged.sh eval-default-004000 .venv/bin/python -m lerobot_robot_exo_hand.heldout eval --root datasets/exo_grasp --fraction 0.1 --seed 0 --variant default --checkpoint outputs/train/RUN-20260920T093202Z/default/checkpoints/004000/pretrained_model --out ../docs/notes/training/runs/RUN-20260920T093202Z/results.jsonl 
```

Decision at 10:10Z: step 5000 is expected at ~10:18:30Z and its evaluation to end ~10:22Z,
leaving ~33 min to 10:55Z for the shutdown checklist. The training runs to 5000 (all five
checkpoints of the plan).
Result (EXIT=0, ended 10:13:25Z): **mae 0.0141**, **mae_near_crossing 0.0595**; per finger thumb
0.0181, index 0.0113, middle 0.0116, ring 0.0138, pinky 0.0156. Both numbers improved on
step 3000 (0.0149 / 0.0634), the crossing number by the largest step so far. Stop rule not
triggered.

### Step-0 baseline (pretrained `lerobot/smolvla_base`, no fine-tune)

Asked by the person at 10:18Z: the held-out error of the pretrained model before any training,
for comparison. Not a training variant. The checkpoint path is a symlink in the agent's
scratchpad to the hub cache snapshot `d9f33c94a60fb382c90dea2164c96845bd955e28`, named
`checkpoints/000000/pretrained_model` so the result line carries step 0. Its preprocessor
carries the base model's own normalization stats, not this dataset's, so the number is what a
non-fine-tuned model does, no more. Started 10:18Z in tmux `work` window
`eval-base-step0`, command exactly as run:

```
cd ~/htn/policy && lambda/run_logged.sh eval-base-step0 .venv/bin/python -m lerobot_robot_exo_hand.heldout eval --root datasets/exo_grasp --fraction 0.1 --seed 0 --variant base-step0 --checkpoint /tmp/claude-1000/-home-ubuntu-htn/b29561c7-35b0-430a-99ba-a6efbc35933b/scratchpad/base-step0/checkpoints/000000/pretrained_model --out ../docs/notes/training/runs/RUN-20260920T093202Z/results.jsonl
```

### Checkpoint 005000

Written 10:19:37Z, `model.safetensors` 906712520 bytes. Evaluation started 10:19Z in tmux
`work` window `eval-default-005000`, command exactly as run:

```
cd ~/htn/policy && lambda/run_logged.sh eval-default-005000 .venv/bin/python -m lerobot_robot_exo_hand.heldout eval --root datasets/exo_grasp --fraction 0.1 --seed 0 --variant default --checkpoint outputs/train/RUN-20260920T093202Z/default/checkpoints/005000/pretrained_model --out ../docs/notes/training/runs/RUN-20260920T093202Z/results.jsonl 
```

Training of `default` ended 10:19:37Z, EXIT=0, 5000/5000 steps in 46:40 (mean 1.79 step/s
including the checkpoint saves and the shared-GPU evaluations). No crash, no retry, no
hyperparameter change. No other variant was run (person's change of plan, see 09:34Z).

## Shutdown checklist

Started 10:20Z (end of rental 10:55:33Z).

### 1. Last checkpoint of each variant

All five checkpoints of `default` have `pretrained_model/model.safetensors` and `config.json`
(step, size of safetensors, size of config.json):

```
001000  safetensors=906712520  config=2493
002000  safetensors=906712520  config=2493
003000  safetensors=906712520  config=2493
004000  safetensors=906712520  config=2493
005000  safetensors=906712520  config=2493
```

**Step-0 baseline, first attempt failed** (`eval-base-step0.log`, EXIT=1 at 10:20Z):
`ValueError: operands could not be broadcast together with shapes (3437,6) (3437,5)`.
Diagnosis: the pretrained `smolvla_base` config carries the 6-dim action space of its own
pretraining data, and its own normalization stats; it is not the step 0 of this fine-tune. The
step 0 of the fine-tune is the base weights with the fine-tune's config and this dataset's
normalizer, which is what `lerobot-train` holds before its first update.
Retry (one time) with a folder in the agent's scratchpad that holds checkpoint 001000's
`config.json`, `train_config.json` and the four pre/post-processor files, and a symlink to the
base model's `model.safetensors` (SmolVLA pads state and action to 32 internally, so the weight
shapes match). Variant name `step0`. Started 10:21Z in tmux `work` window
`eval-step0-retry`, command exactly as run:

```
cd ~/htn/policy && lambda/run_logged.sh eval-step0-retry .venv/bin/python -m lerobot_robot_exo_hand.heldout eval --root datasets/exo_grasp --fraction 0.1 --seed 0 --variant step0 --checkpoint /tmp/claude-1000/-home-ubuntu-htn/b29561c7-35b0-430a-99ba-a6efbc35933b/scratchpad/step0/checkpoints/000000/pretrained_model --out ../docs/notes/training/runs/RUN-20260920T093202Z/results.jsonl
```
Result (EXIT=0, ended 10:21:49Z): **mae 0.0140**, **mae_near_crossing 0.0589**; per finger thumb
0.0180, index 0.0116, middle 0.0114, ring 0.0134, pinky 0.0155. Both numbers improved on
step 4000 (0.0141 / 0.0595), marginally: the curve is flattening. Stop rule never triggered
during the run.
Result of the retry (EXIT=0, ended 10:23:10Z), variant `step0`, step 0: **mae 0.0236**,
**mae_near_crossing 0.0831**; per finger thumb 0.0279, index 0.0253, middle 0.0198, ring
0.0252, pinky 0.0197. This is the fine-tune's starting point on the same held-out frames.
Note the low absolute number of an untrained policy: this dataset's normalizer puts the
prediction near the dataset mean, and most held-out frames are a finger holding still.

### 2. Closing

**Variants.** Only `default` ran (person's change of plan at 09:34Z: rental ends at launch +
90 min, `default` only). `short_chunk`, `train_vlm` and `unfrozen` were not run for that reason;
nothing about them was tested. `default` trained the full 5000 steps without a crash, a retry or
a hyperparameter change; all five checkpoints were evaluated on the same 5 held-out episodes
`[2,16,24,26,48]` (3437 frames, 168 within 0.5 s of a close or a release), full evaluation,
`stride` 1.

**Held-out error, 0..1 command scale, lower is better** (`results.jsonl`):

| variant | step | mae | mae_near_crossing | thumb | index | middle | ring | pinky |
|---|---|---|---|---|---|---|---|---|
| default | 1000 | 0.0192 | 0.0666 | 0.0245 | 0.0157 | 0.0148 | 0.0193 | 0.0216 |
| default | 2000 | 0.0170 | 0.0639 | 0.0207 | 0.0147 | 0.0136 | 0.0173 | 0.0187 |
| default | 3000 | 0.0149 | 0.0634 | 0.0184 | 0.0125 | 0.0118 | 0.0141 | 0.0179 |
| default | 4000 | 0.0141 | 0.0595 | 0.0181 | 0.0113 | 0.0116 | 0.0138 | 0.0156 |
| default | 5000 | 0.0140 | 0.0589 | 0.0180 | 0.0116 | 0.0114 | 0.0134 | 0.0155 |
| step0 (base weights, no fine-tune) | 0 | 0.0236 | 0.0831 | 0.0279 | 0.0253 | 0.0198 | 0.0252 | 0.0197 |

**Best checkpoint of `default`: step 5000**, by both numbers, at
`policy/outputs/train/RUN-20260920T093202Z/default/checkpoints/005000/pretrained_model`
(`model.safetensors` 906712520 bytes). Step 4000 is within noise of it (0.0595 vs 0.0589 near
crossings). The error fell monotonically from step 1000 to 5000 on both numbers, so the plan's
stop rule (rise at two consecutive checkpoints) never fired; the curve is flattening after
4000, and a longer run would likely gain little on this data.

**What it says about the plan's question** ("does the default fine-tune learn the close and the
release at all"): the error near the crossings fell from 0.067 to 0.059, while the error over
all frames fell from 0.019 to 0.014. The crossing error is ~4× the overall error at every
checkpoint: the policy is much better at holding a finger still than at the moment of the
transition, and the held-out evaluation is open-loop (recorded history as input), so it does
not show what the hand does under its own predictions, nor whether the timing of a close is
right. The held-out number is a filter, not the verdict.

**What failed.** Only the first step-0 baseline attempt (`eval-base-step0.log`): the pretrained
`smolvla_base` config has a 6-dim action space and its own normalization stats, so it is not the
step 0 of this fine-tune (see the diagnosis above). The retry with the fine-tune's config and normalizer on the base weights succeeded (variant `step0` in the table): fine-tuning took the near-crossing error from 0.083 to 0.059 (-29 %) and the overall error from 0.024 to 0.014 (-41 %).

**Deserve a test on the hand:** step 5000 first, step 4000 as the fallback (nearly the same
numbers, in case 5000 shows a behaviour the open-loop number does not catch). Steps 1000–3000
only as reference for how the behaviour changes with training.

**Suggested for the next rental** (not done here): `short_chunk` is the untested half of the
plan's question. For the "does the hand ever close on its own" question the evaluation could
also report the max per-frame error and the fraction of frames with error > 0.5, split into
near-crossing and far-from-crossing frames; the MAE alone cannot separate rare large errors
from many small ones.

### 3. Fetch and receipt

`.watchdog-fetch` touched at 10:28:00Z.

Receipt after that touch, first line: `# pull receipt 2026-09-20T10:28:26Z: size and path of each file on the laptop`
Check (size here vs. the receipt), done 10:28:50Z:

```
                  OK   906712520  policy/outputs/train/RUN-20260920T093202Z/default/checkpoints/001000/pretrained_model/model.safetensors
                  OK   906712520  policy/outputs/train/RUN-20260920T093202Z/default/checkpoints/002000/pretrained_model/model.safetensors
                  OK   906712520  policy/outputs/train/RUN-20260920T093202Z/default/checkpoints/003000/pretrained_model/model.safetensors
                  OK   906712520  policy/outputs/train/RUN-20260920T093202Z/default/checkpoints/004000/pretrained_model/model.safetensors
                  OK   906712520  policy/outputs/train/RUN-20260920T093202Z/default/checkpoints/005000/pretrained_model/model.safetensors
                  OK        2825  docs/notes/training/runs/RUN-20260920T093202Z/results.jsonl
                  OK       14923  docs/notes/training/runs/RUN-20260920T093202Z/notes.md
NOT COMPLETE
```

All five `model.safetensors` (906712520 bytes each), `results.jsonl` (2825) and `notes.md` (14923
at that time) are on the laptop at the same size. `checkpoints/last` is a symlink to `005000`
and is not pulled, which is fine. No patch files (no code change was needed). The notes changed
after that pull (this section), so one more fetch follows; its receipt is checked for the final
`notes.md` size before the terminate.

Second receipt (after the notes changed): `# pull receipt 2026-09-20T10:29:33Z`, `notes.md`
16411 bytes here and on the laptop, all five checkpoints and `results.jsonl` unchanged and OK.
A third fetch takes this final paragraph home; then `.watchdog-terminate` at ~10:31Z, 24 min
before the 10:55:33Z end the person asked for. Rental over.
