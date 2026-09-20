"""Kinematics of one finger's linkage. Pure maths, no ROS.

A finger is a 1-DOF chain of three four-bars driven by the servo horn (pivot
names as in htn_description/tools/cad_to_linkage.py and config/linkage.yaml):

    horn G0-P, pushrod P-A, triangle G1-A-B, ternary bar B-M-E,
    long link G2-M-T, binary bar T-U, adapter E-U (carries the contact pad)

G0, G1, G2 are on the base. URDF cannot hold closed loops, so the description
is a tree (each part hangs on ONE of its pivots) and this module supplies the
angles of the passive joints for a given horn angle, which closes the loops.
"""
import math

PIVOTS = ('G0', 'G1', 'G2', 'P', 'A', 'B', 'M', 'E', 'T', 'U')
# Passive joints of the URDF tree, in the order joint_angles() returns them
PASSIVE = ('rod', 'triangle', 'ternary', 'long', 'binary', 'adapter')


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _rot(v, angle):
    c, s = math.cos(angle), math.sin(angle)
    return (c * v[0] - s * v[1], s * v[0] + c * v[1])


def _about(centre, point, angle):
    r = _rot(_sub(point, centre), angle)
    return (centre[0] + r[0], centre[1] + r[1])


def _angle(v):
    return math.atan2(v[1], v[0])


def _wrap(angle):
    return (angle + math.pi) % (2 * math.pi) - math.pi


def _circles(c1, r1, c2, r2, near):
    """The intersection of two circles that is closest to `near`, or None if they miss."""
    d = math.dist(c1, c2)
    if d == 0 or d > r1 + r2 or d < abs(r1 - r2):
        return None
    a = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
    h = math.sqrt(max(r1 * r1 - a * a, 0.0))
    ux, uy = (c2[0] - c1[0]) / d, (c2[1] - c1[1]) / d
    mx, my = c1[0] + a * ux, c1[1] + a * uy
    return min(((mx - h * uy, my + h * ux), (mx + h * uy, my - h * ux)),
               key=lambda p: math.dist(p, near))


class Linkage:
    """`pivots`: name -> (u, v) in the linkage plane, CAD pose (= open hand).
    `closing`: +1 / -1, the sense of horn rotation about +axis that closes the finger."""

    def __init__(self, pivots, closing):
        self.p = {name: tuple(pivots[name]) for name in PIVOTS}
        self.closing = closing

    def solve(self, horn, near=None):
        """Absolute rotation of every part (about +axis, from the CAD pose) for an absolute
        horn rotation, or None where the mechanism cannot assemble. `near` is a previous
        solution: each four-bar has two assemblies, and the hand stays on its own."""
        p = self.p
        near = near or p
        length = lambda a, b: math.dist(p[a], p[b])  # noqa: E731
        P = _about(p['G0'], p['P'], horn)
        A = _circles(P, length('P', 'A'), p['G1'], length('G1', 'A'), near['A'])
        if A is None:
            return None
        triangle = _wrap(_angle(_sub(A, p['G1'])) - _angle(_sub(p['A'], p['G1'])))
        B = _about(p['G1'], p['B'], triangle)
        M = _circles(B, length('B', 'M'), p['G2'], length('G2', 'M'), near['M'])
        if M is None:
            return None
        long = _wrap(_angle(_sub(M, p['G2'])) - _angle(_sub(p['M'], p['G2'])))
        T = _about(p['G2'], p['T'], long)
        ternary = _wrap(_angle(_sub(M, B)) - _angle(_sub(p['M'], p['B'])))
        E = _about(B, (B[0] + p['E'][0] - p['B'][0], B[1] + p['E'][1] - p['B'][1]), ternary)
        U = _circles(T, length('T', 'U'), E, length('E', 'U'), near['U'])
        if U is None:
            return None
        return {
            'horn': horn,
            'rod': _wrap(_angle(_sub(A, P)) - _angle(_sub(p['A'], p['P']))),
            'triangle': triangle, 'ternary': ternary, 'long': long,
            'binary': _wrap(_angle(_sub(U, T)) - _angle(_sub(p['U'], p['T']))),
            'adapter': _wrap(_angle(_sub(U, E)) - _angle(_sub(p['U'], p['E']))),
            'A': A, 'M': M, 'U': U, 'E': E,
        }

    def sweep(self, step=math.radians(0.25), limit=math.radians(200.0)):
        """Solutions from the CAD pose in the closing direction until the mechanism binds.
        'curl' = rotation of the contact pad, the quantity a wearer feels."""
        out, near, horn = [], None, 0.0
        while abs(horn) <= limit:
            solution = self.solve(horn, near)
            if solution is None:
                break
            solution['curl'] = solution['adapter']
            out.append(solution)
            near, horn = solution, horn + self.closing * step
        return out

    def table(self, closed, samples=181, opened=0.0):
        """Passive joint angles at `samples` even steps of the actuated joint q in [opened, closed]
        (q >= 0 closes, whatever the sense of the horn; opened < 0 = a hand that opens past the CAD
        pose). Row i belongs to q = opened + (closed - opened) * i / (samples - 1)."""
        qs = [opened + (closed - opened) * i / (samples - 1) for i in range(samples)]
        start = min(range(samples), key=lambda i: abs(qs[i]))  # the CAD pose: the one known assembly
        rows = [None] * samples
        # Out from the CAD pose both ways, each solution the starting guess of the next
        for order in (range(start, samples), range(start - 1, -1, -1)):
            near = previous = None
            for i in order:
                if previous is None and i != start:
                    near, previous = first, rows[start]
                solution = self.solve(self.closing * qs[i], near)
                if solution is None:
                    raise ValueError(f'the linkage binds at q = {qs[i]:.3f} rad, inside [{opened:.3f}, {closed:.3f}]')
                if i == start:
                    first = solution
                near = solution
                row = relative(solution)
                if previous is not None:  # keep each column continuous: interpolating across a +-pi wrap would spin a part
                    row = tuple(prev + _wrap(value - prev) for prev, value in zip(previous, row))
                rows[i] = previous = row
        return rows


def relative(solution):
    """Absolute part rotations -> the angles of the URDF's passive joints (child relative to
    parent): rod on the horn, ternary on the triangle, binary on the long link, adapter on the
    ternary bar; triangle and long link hang on the base."""
    s = solution
    return (_wrap(s['rod'] - s['horn']), s['triangle'], _wrap(s['ternary'] - s['triangle']),
            s['long'], _wrap(s['binary'] - s['long']), _wrap(s['adapter'] - s['ternary']))


class PassiveJoints:
    """Interpolated lookup q -> passive joint angles; built once, cheap at 100 Hz."""

    def __init__(self, linkage, closed, samples=181, opened=0.0):
        self.opened, self.closed = opened, closed
        self.rows = linkage.table(closed, samples, opened)

    def __call__(self, q):
        x = min(max((q - self.opened) / (self.closed - self.opened), 0.0), 1.0) * (len(self.rows) - 1)
        i = min(int(x), len(self.rows) - 2)
        f = x - i
        return tuple(a + (b - a) * f for a, b in zip(self.rows[i], self.rows[i + 1]))
