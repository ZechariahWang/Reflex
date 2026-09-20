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

REST = 0.05        # fingers hover over the keys, nearly open
PRESS = 0.95       # a key is down: nearly the whole travel (quarter notes)
FAST_PRESS = 0.45  # the quick notes ("one a penny, two a penny"): a shorter stroke, so that the finger
                   # ARRIVES and stands still at the bottom and again at the top before the next one.
                   # Asked for the whole travel in an eighth note, a finger never gets there, turns
                   # around in mid-air and four strokes blur into one wobble
BEAT_S = 0.7       # one quarter note (~86 bpm)
DOWN_SHARE = 0.5   # of a note's time the finger goes down and stays; the rest of it, it comes back up

# How fast a finger moves is the HAL's business (max_speed 4.0 of the travel per second and
# max_accel 60 by default; the real servos reach what `servos.torque_limit` lets them). With
# those, simulated on the HAL's own sweep: a quarter note reaches the full PRESS, and each of
# the four quick strokes reaches FAST_PRESS and is back at REST before the next one.

# (note, beats); "-" is a rest
TUNE = [
    ("B", 1), ("A", 1), ("G", 1), ("-", 1),
    ("B", 1), ("A", 1), ("G", 1), ("-", 1),
    ("G", 0.5), ("G", 0.5), ("G", 0.5), ("G", 0.5), ("A", 0.5), ("A", 0.5), ("A", 0.5), ("A", 0.5),
    ("B", 1), ("A", 1), ("G", 1), ("-", 1),
]


def pose(pressed=None, depth=PRESS):
    return [depth if finger == pressed else REST for finger in FINGERS]


def steps():
    out = [(pose(), 1.0)]  # hands over the keys first
    for note, beats in TUNE:
        seconds = beats * BEAT_S
        if note == "-":
            out.append((pose(), seconds))
        else:
            depth = PRESS if beats >= 1 else FAST_PRESS
            out.append((pose(NOTE_FINGER[note], depth), seconds * DOWN_SHARE))
            out.append((pose(), seconds * (1.0 - DOWN_SHARE)))
    return out


if __name__ == "__main__":
    for values, seconds in steps():
        print(f"{seconds:5.2f} s  " + "  ".join(f"{finger[:3]} {value:.2f}" for finger, value in zip(FINGERS, values)))
