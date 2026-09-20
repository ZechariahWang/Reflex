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

REST = 0.15    # fingers hover over the keys, a little curled
PRESS = 0.55   # a key is down
BEAT_S = 1.2   # one quarter note. Slow on purpose: the HAL moves a finger at 2.0 of its travel
               # per second at most (and eases in and out), so the 0.4 of a press takes ~0.3 s
               # down and ~0.3 s up - exactly what an eighth note (half a beat) has
DOWN_SHARE = 0.5  # of a note's time the key is down; the rest of it the finger comes back up

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
