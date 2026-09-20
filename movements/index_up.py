"""Stick up the index finger for three seconds, then bring it down.

The other four fingers curl into a loose fist and stay there; the index finger stays open
(pointing up) for HOLD_S, then curls down to the others. The hand relaxes at the end.
"""

TITLE = "Index finger up"
DESCRIPTION = "index up for 3 s over a loose fist, then down"

FINGERS = ["thumb", "index", "middle", "ring", "pinky"]

RELAXED = 0.15  # start and end: every finger nearly open
CURLED = 0.8    # the fist: not the whole travel, a person's hand may be inside
UP = 0.0        # the index finger, straight
HOLD_S = 3.0    # how long the index finger stays up


def steps():
    return [
        ([RELAXED] * 5, 0.5),
        ([CURLED, UP, CURLED, CURLED, CURLED], HOLD_S),  # fist, index up: the hold starts once the hand arrived
        ([CURLED] * 5, 1.0),                             # index down to the others
        ([RELAXED] * 5, 0.5),
    ]


if __name__ == "__main__":
    for values, seconds in steps():
        print(f"{seconds:5.2f} s  " + "  ".join(f"{finger[:3]} {value:.2f}" for finger, value in zip(FINGERS, values)))
