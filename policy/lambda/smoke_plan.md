# Smoke plan

`launch.sh --smoke` puts this file in the place of `docs/notes/training/plan.md` on the instance.
The dataset is fake (noise images, sine-wave fingers): the numbers have no meaning. The goal is to
run each part of the `exo-trainer` skill one time: two variants, one checkpoint wake and one
evaluation for each, the closing notes, the shutdown checklist. Do not retry a variant more than
once, and do not wait for a better number.

```yaml
heldout: {fraction: 0.2, seed: 0}
stop_rule: "none: each variant runs its 50 steps"
common: "--policy.path=lerobot/smolvla_base --policy.device=cuda --policy.push_to_hub=false --batch_size=8 --save_freq=50 --wandb.enable=false"
variants:
  - {name: default,     args: "--steps=50"}
  - {name: short_chunk, args: "--steps=50 --policy.chunk_size=20 --policy.n_action_steps=20"}
```
