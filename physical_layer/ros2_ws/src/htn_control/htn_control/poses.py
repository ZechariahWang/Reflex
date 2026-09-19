"""Pre-written hand movements.

Values are normalized finger positions in FINGERS order
(thumb, index, middle, ring, pinky): 0 = open, 1 = closed.
"""

POSES = {
    'open':      [0.0, 0.0, 0.0, 0.0, 0.0],
    'fist':      [1.0, 1.0, 1.0, 1.0, 1.0],
    'point':     [1.0, 0.0, 1.0, 1.0, 1.0],
    'peace':     [1.0, 0.0, 0.0, 1.0, 1.0],
    'three':     [1.0, 0.0, 0.0, 0.0, 1.0],
    'thumbs up': [0.0, 1.0, 1.0, 1.0, 1.0],
    'rock':      [1.0, 0.0, 1.0, 1.0, 0.0],
    'call me':   [0.0, 1.0, 1.0, 1.0, 0.0],
    'pinch':     [0.7, 0.7, 0.0, 0.0, 0.0],
    'half curl': [0.5, 0.5, 0.5, 0.5, 0.5],
}

# Movements over time: a list of (pose, seconds to stay on it before the next).
# A pose is a name from POSES or a list of 5 values. The last pose is held.
SEQUENCES = {
    'wave': [
        ([0.0, 0.0, 0.0, 0.0, 1.0], 0.25),
        ([0.0, 0.0, 0.0, 1.0, 1.0], 0.25),
        ([0.0, 0.0, 1.0, 1.0, 1.0], 0.25),
        ([0.0, 1.0, 1.0, 1.0, 1.0], 0.25),
        ('fist', 0.5),
        ([1.0, 1.0, 1.0, 1.0, 0.0], 0.25),
        ([1.0, 1.0, 1.0, 0.0, 0.0], 0.25),
        ([1.0, 1.0, 0.0, 0.0, 0.0], 0.25),
        ([1.0, 0.0, 0.0, 0.0, 0.0], 0.25),
        ('open', 0.0),
    ],
    'grab + release': [
        ('open', 0.6),
        ('half curl', 0.4),
        ('fist', 1.5),
        ('open', 0.0),
    ],
    'count': [
        ('fist', 0.7),
        ('point', 0.7),
        ('peace', 0.7),
        ([1.0, 0.0, 0.0, 0.0, 1.0], 0.7),
        ([1.0, 0.0, 0.0, 0.0, 0.0], 0.7),
        ('open', 0.0),
    ],
}


def resolve(pose):
    """Pose name or list of values -> list of 5 floats."""
    return list(POSES[pose]) if isinstance(pose, str) else list(pose)
