# movements

Pre-written movements of the hand, played from the web console (Episodes bar -> the Movement
dropdown -> Play). One Python file = one movement; the backend lists every `*.py` here whose name
does not start with `_`. Add a file, reload the page, it is in the dropdown.

A movement file has:

```python
TITLE = "Hot cross buns"             # the name in the dropdown
DESCRIPTION = "one line, optional"

def steps():
    """The movement: a list of (pose, seconds). The pose is sent to /hand/command, then nothing
    is sent for `seconds`. A pose is 5 values in the order thumb, index, middle, ring, pinky,
    0 = open .. 1 = closed."""
    return [([0, 0, 0, 0, 0], 0.5), ([0, 1, 1, 0, 0], 1.0)]
```

Rules the backend checks: at most 2000 steps, each 0 < seconds <= 30, values are clamped to 0..1.
The HAL still rate-limits every move (`max_speed` 4.0 of the travel per second: a full close takes ~0.3 s, a stroke of depth d about d / 4 + 0.07 s) and the contact stop
still applies: a movement cannot go faster or push harder than a slider can. A movement can play
while an episode is being recorded (that is a way to record demonstrations), not during a replay.

Try one without the console: `python3 movements/hot_cross_buns.py` prints its steps.
