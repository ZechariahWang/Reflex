#!/usr/bin/env python3
"""Fusion 360 export -> meshes/ and config/linkage.yaml.

The fusion2urdf export of the hand has every part as an STL in assembly
coordinates (mm), but only the joints somebody defined in Fusion - two of about
fifty. The pin holes are all there though, so the mechanism is read off the
geometry: a hole shared by two parts is a pivot between them.

Every finger turns out to be the same 1-DOF chain of three four-bars:

    servo horn --P-- pushrod --A-- triangle --B-- ternary bar --E-- adapter (+ contact pad)
        |G0                          |G1              |M                |U
       base                         base          long link --T-- binary bar
                                                      |G2
                                                     base

Run it again after a new export (needs numpy, trimesh, fast-simplification):

    python3 tools/cad_to_linkage.py ~/Downloads/URDF_description
"""
import argparse
import itertools
import math
import sys
from pathlib import Path

import numpy as np
import trimesh
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'htn_control'))
from htn_control.linkage import PIVOTS, Linkage  # noqa: E402  (the solver the ROS side uses)

PACKAGE = Path(__file__).resolve().parents[1]
# CAD name -> contract name (finger order of the repo), and the normal of the linkage plane
FINGERS = {'thumb': ('thumb', 'z'), 'pointer': ('index', 'x'), 'middle': ('middle', 'x'),
           'ring': ('ring', 'x'), 'pinky': ('pinky', 'x')}
CAD_PARTS = ['horn', 'link_1', 'triangle', 'inner_link_1', 'inner_link_2', 'long_link', 'adapter', 'contact']
ODD_FILES = {('thumb', 'inner_link_1'): 'thumb inner link 1.stl'}
PIN_RADII_MM = (1.4, 3.2)
CURL_CLOSED_DEG = 90.0  # rotation of the contact pad that counts as "fully closed"
# Triangle budget per mesh: CAD tessellation is far finer than any viewer needs
MAX_FACES = {'base': 22000, 'wearer': 9000, 'adapter': 3000, 'contact': 4000, 'horn': 2500}
DEFAULT_MAX_FACES = 1500


def mesh_path(export, cad_finger, part):
    if (cad_finger, part) in ODD_FILES:
        return export / 'meshes' / ODD_FILES[(cad_finger, part)]
    for name in (f'{cad_finger}_{part}_1.stl', f'{cad_finger}_{part}_1_1.stl'):
        if (export / 'meshes' / name).exists():
            return export / 'meshes' / name
    raise FileNotFoundError(f'no mesh for {cad_finger} {part}')


def pin_holes(mesh, axis):
    """Centres (in the plane normal to `axis`) of the circular holes that run along `axis`."""
    keep = [i for i in range(3) if i != axis]
    walls = mesh.faces[np.abs(mesh.face_normals[:, axis]) < 0.2]  # faces parallel to the axis
    centres = set()
    for component in trimesh.graph.connected_components(
            np.vstack([walls[:, [0, 1]], walls[:, [1, 2]]]), min_len=8):
        points = np.unique(np.round(mesh.vertices[component][:, keep], 3), axis=0)
        if not 6 <= len(points) <= 4000:
            continue
        # Least-squares circle; the outer contour of a part is not a circle and drops out
        (cx, cy, c), *_ = np.linalg.lstsq(np.c_[2 * points, np.ones(len(points))], (points ** 2).sum(1), rcond=None)
        radius = math.sqrt(max(c + cx * cx + cy * cy, 0.0))
        fit = np.abs(np.linalg.norm(points - [cx, cy], axis=1) - radius).max()
        if fit < 0.05 and PIN_RADII_MM[0] <= radius <= PIN_RADII_MM[1]:
            centres.add((round(float(cx), 2), round(float(cy), 2)))
    return sorted(centres)


def shared(a, b):
    return [p for p in a for q in b if abs(p[0] - q[0]) < 0.06 and abs(p[1] - q[1]) < 0.06]


def find_pivots(holes):
    """Name the ten pivots by their role. Which of the two inner bars is the ternary one differs
    between the thumb and the fingers, so it is found, not assumed."""
    def one(a, b):
        found = shared(holes[a], holes[b])
        if len(found) != 1:
            raise ValueError(f'{a} and {b} share {len(found)} holes, expected 1')
        return list(found[0])

    inner = ['inner_link_1', 'inner_link_2']
    ternary = next(bar for bar in inner if shared(holes['triangle'], holes[bar]))
    binary = next(bar for bar in inner if bar != ternary)
    pivots = {'G0': one('base', 'horn_axis'), 'G1': one('base', 'triangle'), 'G2': one('base', 'long_link'),
              'P': one('horn', 'link_1'), 'A': one('link_1', 'triangle'), 'B': one('triangle', ternary),
              'M': one(ternary, 'long_link'), 'E': one(ternary, 'adapter'),
              'T': one(binary, 'long_link'), 'U': one(binary, 'adapter')}
    assert list(pivots) == list(PIVOTS)
    return pivots, ternary, binary


def decimate(mesh, max_faces):
    if len(mesh.faces) <= max_faces:
        return mesh
    return mesh.simplify_quadric_decimation(face_count=max_faces)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('export', type=Path, help='the fusion2urdf export folder (has meshes/)')
    export = parser.parse_args().export.expanduser()
    out_meshes = PACKAGE / 'meshes'
    out_meshes.mkdir(exist_ok=True)

    base = trimesh.load(export / 'meshes' / 'base_link.stl')
    # The CAD base body includes a mannequin hand and forearm: by far its largest connected
    # piece. It is the wearer, not the machine, so it becomes a mesh of its own.
    pieces = sorted(base.split(only_watertight=False), key=lambda piece: -abs(piece.volume))
    wearer, frame = pieces[0], trimesh.util.concatenate(pieces[1:])
    decimate(wearer, MAX_FACES['wearer']).export(out_meshes / 'wearer.stl')
    decimate(frame, MAX_FACES['base']).export(out_meshes / 'base.stl')
    base_holes = {axis: pin_holes(base, 'xyz'.index(axis)) for axis in 'xz'}

    fingers = {}
    for cad_finger, (finger, axis) in FINGERS.items():
        a = 'xyz'.index(axis)
        meshes = {part: trimesh.load(mesh_path(export, cad_finger, part)) for part in CAD_PARTS}
        holes = {part: pin_holes(mesh, a) for part, mesh in meshes.items() if part != 'contact'}
        holes['base'] = base_holes[axis]
        # The horn touches the base at its screws as well; its axis is the hole the rod pin is not
        rod_pin = shared(holes['horn'], holes['link_1'])
        holes['horn_axis'] = [h for h in shared(holes['horn'], holes['base']) if h not in rod_pin
                              and all(abs(h[0] - s[0]) + abs(h[1] - s[1]) > 0.1 for s in rod_pin)]
        # ... and of those, the one in the middle of the screw pattern
        if len(holes['horn_axis']) > 1:
            centre = np.mean(holes['horn_axis'], axis=0)
            holes['horn_axis'] = [min(holes['horn_axis'], key=lambda h: np.hypot(*(np.array(h) - centre)))]
        pivots, ternary, binary = find_pivots(holes)

        # Which way closes: the way the pad travels far (the other way locks within ~30 deg)
        sweeps = {d: Linkage(pivots, d).sweep() for d in (+1, -1)}
        closing = max(sweeps, key=lambda d: abs(sweeps[d][-1]['curl']))
        sweep = sweeps[closing]
        lock = abs(sweep[-1]['horn'])
        closed = next(abs(s['horn']) for s in sweep if abs(s['curl']) >= math.radians(CURL_CLOSED_DEG))

        roles = {'horn': 'horn', 'rod': 'link_1', 'triangle': 'triangle', 'ternary': ternary,
                 'long': 'long_link', 'binary': binary, 'adapter': 'adapter', 'contact': 'contact'}
        for role, part in roles.items():
            decimate(meshes[part], MAX_FACES.get(role, DEFAULT_MAX_FACES)).export(out_meshes / f'{finger}_{role}.stl')
        plane = float(np.mean([meshes[p].bounds[:, a].mean() for p in ('link_1', 'triangle', 'long_link')]))
        fingers[finger] = {
            'axis': axis, 'plane': round(plane, 2), 'closing': closing, 'pivots': pivots,
            'closed_rad': round(closed, 4), 'lock_rad': round(lock, 4),
            'open_lock_rad': round(abs(sweeps[-closing][-1]['horn']), 4),
        }
        print(f'{finger:7s} axis {axis}  closes {"+" if closing > 0 else "-"}  '
              f'closed at {math.degrees(closed):5.1f} deg horn, locks at {math.degrees(lock):5.1f} deg')

    header = ('# GENERATED by tools/cad_to_linkage.py from the Fusion export - do not edit by hand.\n'
              '# Millimetres, CAD assembly frame. `pivots` are in the linkage plane: (y, z) for axis x,\n'
              '# (x, y) for axis z, so counter-clockwise there is a positive turn about +axis.\n'
              '# closed_rad = servo horn angle for a 90 deg curl of the contact pad; lock_rad = where\n'
              '# the mechanism binds when closing, open_lock_rad = where it binds when opening PAST the CAD\n'
              '# pose (nothing else stops it sooner). The CAD pose is the open hand.\n')
    (PACKAGE / 'config' / 'linkage.yaml').write_text(
        header + yaml.safe_dump({'curl_closed_deg': CURL_CLOSED_DEG, 'fingers': fingers}, sort_keys=False))
    total = sum(f.stat().st_size for f in out_meshes.glob('*.stl'))
    print(f'{len(list(out_meshes.glob("*.stl")))} meshes, {total / 1e6:.1f} MB -> {out_meshes}')


if __name__ == '__main__':
    main()
