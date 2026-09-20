# Training plan

A person writes this file before a rental; `policy/lambda/launch.sh` refuses to start without
it. Only the agent on the instance (`.claude/skills/exo-trainer`) reads it, and it reads the
prose too: write here what it cannot see from the data (for example "the lighting changed after
episode 30"). The dataset is not named here: it is `LAMBDA_DATASET` in `policy/lambda/.env`.
Format: `../../specs/lambda-training-design.md`, Plan format.

## This rental

First rental on real data. Goal: find out if the default fine-tune learns the close and the
release at all, and if a shorter action chunk helps. `save_freq=1000` gives 5 checkpoints for
each variant; one checkpoint is ~1 GB on the way home.

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
