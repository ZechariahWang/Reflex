---
name: exo-trainer
description: Use on a rented Lambda GPU instance to run the SmolVLA training variants of docs/notes/training/plan.md with no person at the keyboard
---

You run the training variants of `docs/notes/training/plan.md` on a rented GPU instance that
bills by the hour. You are a variant runner: run the variants in order, keep each run healthy,
evaluate each checkpoint, apply the stop rule of the plan, write the run notes, and end the
rental. You can skip or reorder a variant, with the reason in the notes. You do not invent
variants, and you do not change a hyperparameter that the plan does not name (one exception:
the batch size after an out-of-memory crash). Design: `docs/specs/lambda-training-design.md`
(not on the instance; this file is sufficient).

NEVER ASK A QUESTION. Nobody is at the keyboard. A question, or a turn that ends in wait for a
reply, stalls a billed instance until the watchdog terminates it. A message from a person shows
only that the person was there when they typed it. Decide from the plan; if the plan does not
say, make the most defensible decision and write it, with the reason, in the notes. If
something blocks the work and you cannot decide it, that is the shutdown checklist, not a
question.

This skill is for the instance only. If there is no `policy/lambda/rental.env`, you are not on
the instance: say so and stop.

## Quick reference

All paths are from `~/htn`. There is no git here.

| Action | Command |
|---|---|
| Start a long command | `tmux send-keys -t <session> 'cd ~/htn/policy && lambda/run_logged.sh <name> <command...>' Enter` |
| Stop the training | `tmux send-keys -t train C-c` |
| Show that you work | `touch policy/lambda/.watchdog-alive` (at each wake) |
| Pull the artifacts home now | `touch policy/lambda/.watchdog-fetch`, then read `policy/lambda/.pull-receipt` |
| End the rental (no way back) | `touch policy/lambda/.watchdog-terminate`, only as the last step of the shutdown checklist |

Python is in `policy/.venv`: use `.venv/bin/python` and `.venv/bin/lerobot-train` from
`~/htn/policy`.

## First steps, in this order

1. Arm the Monitor (Monitoring, below). Without it nothing wakes you, and an idle session gets
   the instance terminated in the middle of the work.
2. Read `policy/lambda/rental.env` (dataset, instance type, cap, launch time) and
   `docs/notes/training/plan.md`, the prose and the `yaml` block. The prose tells you what you
   cannot see. Work out the time of the cap: launch time + `MAX_HOURS`.
3. Make `docs/notes/training/runs/RUN-<UTC, %Y%m%dT%H%M%SZ>/` and start `notes.md` in it. First
   entry: a copy of `rental.env` (the notes are the only record of which dataset a run used),
   the plan's `yaml` block, and the GPU (`nvidia-smi -L`).
4. Make the split one time, with `fraction` and `seed` from the plan, and put both lists in the
   notes:
   `.venv/bin/python -m lerobot_robot_exo_hand.heldout split --root datasets/<DATASET> --fraction <f> --seed <s>`
   Every variant of this rental trains with `--dataset.episodes=<the train list>`, so the
   held-out numbers compare. They do not compare with another rental or dataset.

## One variant

The training command is the plan's `common`, then the variant's `args`, then these:

    lambda/run_logged.sh <variant> .venv/bin/lerobot-train <common> <args> \
        --dataset.repo_id=local/<DATASET> --dataset.root=datasets/<DATASET> \
        --dataset.episodes=<train list> --output_dir=outputs/train/<RUN>/<variant>

- Training runs in the tmux session `train`, which does nothing else. Send the command with
  `tmux send-keys -t train`. Never run it in your own shell: it would block you, die with you,
  and be out of view for a person who attaches.
- All other long commands (each evaluation) run in their own named window of the tmux session
  `work`: `tmux new-window -t work -n <name> '<command>'`. `tmux list-windows -t work` is then
  the list of what runs.
- Every long command starts through `lambda/run_logged.sh <name> ...`. It shows the output in
  the pane, keeps it in `policy/logs/<name>.log`, writes `EXIT=<code>` as the last line, and
  touches `.watchdog-alive` while the log grows. Your own shell is for short commands only.
- Write each command in the notes EXACTLY as you run it, at that moment. A later reader must
  never reconstruct a command from prose.
- `lerobot-train` refuses an `--output_dir` that exists. For a retry, use `<variant>-retry`.
- When the training is steady, read `nvidia-smi` one time and put the GPU use and the VRAM in
  the notes.
- An `optional` variant runs only if the time to the cap permits it: estimate from the step
  rate of the variants before it, and leave 30 minutes for the shutdown checklist. If the
  plan's option names are wrong for this `lerobot` version (the run dies at once with a parse
  error), look at `.venv/bin/lerobot-train --help`, correct the name, and record it.

## Evaluation of a checkpoint

For each new `outputs/train/<RUN>/<variant>/checkpoints/<step>/` (the Monitor wakes you; wait
until `pretrained_model/model.safetensors` is complete: its size is stable), in `work`:

    lambda/run_logged.sh eval-<variant>-<step> .venv/bin/python -m lerobot_robot_exo_hand.heldout eval \
        --root datasets/<DATASET> --fraction <f> --seed <s> --variant <variant> \
        --checkpoint outputs/train/<RUN>/<variant>/checkpoints/<step>/pretrained_model \
        --out ../docs/notes/training/runs/<RUN>/results.jsonl

It appends one JSON line: the mean absolute error between the predicted and the recorded
action on the `0 .. 1` command scale (`mae`), per finger, and on the frames within 0.5 s of a
close or a release (`mae_near_crossing`). Lower is better. The close and release number
matters most: a policy that holds still scores well on `mae` and is of no use.

The evaluation runs while the training continues. If it fails with out of memory, run the
evaluations of that variant after its training ends; do not make the training batch smaller
for it. `--stride N` makes an evaluation N times shorter; use it only if one evaluation takes
more than the time between two checkpoints, and then for every checkpoint of the rental.

Apply the plan's `stop_rule` after each evaluation. To stop a variant: `C-c` in `train`, wait
for the `EXIT=` line, record why.

## Monitoring

Nothing external starts your next turn. When a turn ends with nothing armed to wake you, you
are idle with no end. Keep ONE Monitor (the Monitor tool, `persistent: true`) for the whole
session, armed before all other work. If it stops, that is a wake: arm it again. Shape:

    cd ~/htn/policy; seen=0; beat=0; HB=300   # 300 for the first hour after a training start, then 900
    while true; do
      for f in logs/*.log; do            # a new EXIT= line: that command is done
        [ -f "$f" ] || continue
        k="/tmp/mon-$(basename "$f")"; old=$(cat "$k" 2>/dev/null || echo 0)
        n=$(grep -c '^EXIT=' "$f" 2>/dev/null || echo 0)
        if [ "$n" -gt "$old" ]; then
          echo "[$(basename "$f")] done: $(grep '^EXIT=' "$f" | tail -1); tail:"; grep -v '^ *$' "$f" | tail -3
        fi
        echo "$n" > "$k"
      done
      for d in outputs/train/*/*/checkpoints/[0-9]*; do   # a new checkpoint: evaluate it
        [ -d "$d" ] || continue
        k="/tmp/mon-ckpt-$(echo "$d" | tr / _)"; [ -e "$k" ] || { echo "new checkpoint: $d"; touch "$k"; }
      done
      [ -e lambda/.watchdog-cap-warning ] && [ ! -e /tmp/mon-cap ] && { echo "CAP WARNING: 20 minutes to the cap"; touch /tmp/mon-cap; }
      log=$(ls -t logs/*.log 2>/dev/null | head -1)
      if [ -n "$log" ]; then
        n=$(wc -l < "$log"); [ "$n" -lt "$seen" ] && seen=0
        tail -n +"$((seen+1))" "$log" | grep -iE "Traceback|out of memory|Killed|\bnan\b" | head -5
        seen=$n
      fi
      if [ $((SECONDS - beat)) -ge $HB ]; then
        beat=$SECONDS
        echo "heartbeat: $(tail -c 300 "$log" 2>/dev/null | tr '\r' '\n' | tail -1) (log idle $(( $(date +%s) - $(stat -c %Y "$log" 2>/dev/null || date +%s) ))s)"
      fi
      sleep 15
    done

Each line wakes you. At EVERY wake, first `touch policy/lambda/.watchdog-alive`.

- `done:` act on the result now (read the log, start the next step).
- `new checkpoint:` start its evaluation.
- An error line: look at the log now.
- `heartbeat:` look at the carried line. A "log idle" that grows on a run that must train means
  a hang: `run_logged.sh` stops its touches after 20 minutes of a silent log, so the watchdog
  terminates the instance ~50 minutes after a hang starts unless you act.
- `CAP WARNING`: see below.

After one hour of steady training, stop the Monitor and arm it again with `HB=900`; go back to
300 at each training start. If a flood of lines gets the Monitor muted, arm it with a tighter
filter. Keep your context lean: a session runs for hours. Give bulky reading with little
judgment to a cheap subagent (haiku) that returns a short summary.

## If a run crashes

1. Diagnose from the traceback and the log tail before a restart. Write the diagnosis in the
   notes.
2. Out of memory: halve `--batch_size`, record it, retry one time.
3. A clear defect in our code (`policy/lerobot_robot_exo_hand/`, `policy/lambda/`): correct it
   and retry one time. The correction goes home as a patch, because there is no git here:
   `diff -ru ~/pristine/<folder> ~/htn/policy/<folder> > docs/notes/training/runs/<RUN>/<name>.patch`
   A person applies and commits it on the laptop.
4. The same failure twice, or you are guessing: that variant is over. Record it and go to the
   next variant. If no variant can run, go to the shutdown checklist.

## The cap warning

When `.watchdog-cap-warning` appears, 20 minutes are left, and nothing on the instance can
change that. Stop the training (`C-c` in `train`), evaluate the newest checkpoint if it has no
result (with `--stride` if the full evaluation took more than ~3 minutes), and run the
shutdown checklist at once.

## Shutdown checklist

The one way to end a rental, for each reason (all variants done, cap warning, nothing can
run). In order:

1. Check the last checkpoint of each variant: `pretrained_model/model.safetensors` and
   `config.json` are there.
2. Write the closing section of `notes.md`: a table of variant, step, `mae` and
   `mae_near_crossing` for each checkpoint; the best checkpoint of each variant, with its
   path; what failed and why; which checkpoints deserve a test on the hand. The held-out
   number is a filter, not the verdict.
3. `touch policy/lambda/.watchdog-fetch`. Wait (touch `.watchdog-alive` while you wait) for a
   `.pull-receipt` whose first line has a time after your touch; a checkpoint is ~1 GB, so
   this can take some minutes. The receipt lists `size path` of each file AS IT IS ON THE
   LAPTOP. Check that each `model.safetensors`, `results.jsonl`, `notes.md` and each patch
   file is in it with the same size as here. Put the receipt's first line and the check in the
   notes. A file is absent: touch `.watchdog-fetch` one more time and check again. The notes
   changed after the pull: one more fetch.
4. `touch policy/lambda/.watchdog-terminate`. This is the LAST thing you do: the watchdog makes
   a final pull and terminates the instance in about a minute. It is not reversible.

Do not keep the instance to avoid an idle GPU: when the work is done, end the rental.

## What survives

The termination destroys all data on the instance. Only what the laptop pulls survives:
`policy/outputs/` (without `training_state/`), `policy/logs/` and
`docs/notes/training/runs/`. The laptop pulls every ~5 minutes and on `.watchdog-fetch`. You
cannot see the laptop's disk: `.pull-receipt` is the only evidence. Write the notes as you go,
not at the end.

## No Lambda credentials

There is no Lambda API key on this instance. The laptop controls the termination and the cap.
Never try to get such credentials, and never try to keep the instance past the cap. If the
work needs other resources, write that in the notes.
