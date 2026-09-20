"""Hot cross buns on three keys, one finger per note.

The tune has three notes, B A G: index, middle and ring finger, side by side on the keys as a
hand lies on a piano. A note is a key press: the finger goes down to PRESS and comes back to
REST before the next note. The thumb and the pinky stay at REST.

    B  A  G  -  | B  A  G  -  | G G G G A A A A | B  A  G  -
"""

TITLE = "Hot cross buns"
DESCRIPTION = "B A G on index, middle, ring: three key presses per bar"

FINGERS = ["thumb", "index", "middle", "ring", "pinky"]
NOTE_FINGER = {"B": "index", "A": "middle", "G": "ring"}

REST = 0.05    # fingers hover over the keys, nearly open
PRESS = 0.95   # a key is down: nearly the whole travel
BEAT_S = 0.7   # one quarter note (~86 bpm)
DOWN_SHARE = 0.5  # of a note's time the finger goes down; the rest of it, it comes back up

# How far a finger really gets is the HAL's business, not this file's: it moves a finger at
# `max_speed` (2.0 of its travel per second by default, eased in and out by `max_accel`), so in
# the 0.35 s of a quarter note a finger gets 0.72 of its travel down, and in the 0.175 s of an
# eighth note 0.36 (the HAL's own sweep, simulated) - PRESS is then a direction more than a
# place. Launched faster, a quarter note reaches the full 0.90 and an eighth note 0.72:
#     ros2 launch htn_launch hardware.launch.py max_speed:=4.0 max_accel:=60.0
# (both launch files take them). On the real hand that is only as fast as the servos can go
# with `servos.torque_limit` of hand_params.yaml, and everything a finger meets, it meets harder.

# (note, beats); "-" is a rest
TUNE = [
    ("B", 1), ("A", 1), ("G", 1), ("-", 1),
    ("B", 1), ("A", 1), ("G", 1), ("-", 1),
    ("G", 0.5), ("G", 0.5), ("G", 0.5), ("G", 0.5), ("A", 0.5), ("A", 0.5), ("A", 0.5), ("A", 0.5),
    ("B", 1), ("A", 1), ("G", 1), ("-", 1),
]


def pose(pressed=None):
    return [PRESS if finger == pressed else REST for finger in FINGERS]


def steps():
    out = [(pose(), 1.0)]  # hands over the keys first
    for note, beats in TUNE:
        seconds = beats * BEAT_S
        if note == "-":
            out.append((pose(), seconds))
        else:
            out.append((pose(NOTE_FINGER[note]), seconds * DOWN_SHARE))
            out.append((pose(), seconds * (1.0 - DOWN_SHARE)))
    return out


if __name__ == "__main__":
    for values, seconds in steps():
        print(f"{seconds:5.2f} s  " + "  ".join(f"{finger[:3]} {value:.2f}" for finger, value in zip(FINGERS, values)))
