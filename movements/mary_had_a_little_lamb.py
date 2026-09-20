"""Mary had a little lamb, the short version, on three keys, one finger per note.

Only "Mary had a little lamb, its fleece was white as snow": that line needs three notes, C D E
(the G of "little lamb, little lamb" is in the part that is left out). It is a LEFT hand, so the
higher note is nearer the thumb: ring on C, middle on D, index on E, side by side on the keys; the
thumb and the pinky stay at REST. A note is a key press: the finger goes down to PRESS and comes
back to REST before the next note, so the repeated notes (E E E E) are separate strokes.

    E D C D | E E E E | D D E D | C - - -
"""

TITLE = "Mary had a little lamb"
DESCRIPTION = "short version, C D E on ring, middle, index (left hand): no thumb, quarter notes at ~86 bpm"

FINGERS = ["thumb", "index", "middle", "ring", "pinky"]
NOTE_FINGER = {"C": "ring", "D": "middle", "E": "index"}

REST = 0.05        # fingers hover over the keys, nearly open
PRESS = 0.95       # a key is down: nearly the whole travel
BEAT_S = 0.7       # one quarter note (~86 bpm): the tempo at which hot_cross_buns' quarter notes
                   # reach the full PRESS and are back at REST before the next one (HAL max_speed 4.0)
DOWN_SHARE = 0.5   # of a quarter note's time the finger goes down and stays; the rest of it, it comes back up
RELEASE_S = BEAT_S * (1.0 - DOWN_SHARE)  # a long note holds the key and still comes up in this time

# (note, beats); "-" is a rest
TUNE = [
    ("E", 1), ("D", 1), ("C", 1), ("D", 1),
    ("E", 1), ("E", 1), ("E", 1), ("E", 1),
    ("D", 1), ("D", 1), ("E", 1), ("D", 1),
    ("C", 4),
]


def pose(pressed=None):
    return [PRESS if finger == pressed else REST for finger in FINGERS]


def steps():
    out = [(pose(), 1.0)]  # hand over the keys first
    for note, beats in TUNE:
        seconds = beats * BEAT_S
        if note == "-":
            out.append((pose(), seconds))
        else:
            out.append((pose(NOTE_FINGER[note]), seconds - RELEASE_S))
            out.append((pose(), RELEASE_S))
    return out


if __name__ == "__main__":
    for values, seconds in steps():
        print(f"{seconds:5.2f} s  " + "  ".join(f"{finger[:3]} {value:.2f}" for finger, value in zip(FINGERS, values)))
    print(f"total {sum(seconds for _, seconds in steps()):.1f} s")
