#!/usr/bin/env python3
"""Geometry-only Fusion export -> the static parts the hand did not have yet.

The "links only, no joints" exporter writes every body as its own STL (metres,
assembly frame) under generic names, duplicates included. Names are useless,
positions are not: the frame and the pose are the ones of the export the
linkage was read from (tools/cad_to_linkage.py). So every body that lies on a
mesh this package already has is known - linkage, base or the mannequin - and
whatever lies on none of them is new: the RealSense, its bracket, the PCB.

Writes meshes/camera.stl, camera_mount.stl, electronics.stl and
config/static_parts.yaml (where the camera sits and which way it looks).

    python3 tools/cad_static_parts.py ~/Downloads/geometry_export_xxxx

Needs numpy, scipy, trimesh, fast-simplification. Run cad_to_linkage.py first
if the mechanism itself changed; this tool stops if it does not recognise it.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import trimesh
import yaml
from scipy.spatial import cKDTree

PACKAGE = Path(__file__).resolve().parents[1]
STATIC = ('camera', 'camera_mount', 'electronics')
ON_SURFACE_MM = 1.0   # the package meshes are decimated: allow for that
# Share of a body's vertices on known surfaces that makes it known. Measured on the first such
# export: known bodies score 0.61 .. 1.0 (decimation costs the thin ones), new ones 0 .. 0.23.
KNOWN_SHARE = 0.45
D435_MM = (90.0, 25.0, 25.0)
PCB_THICKNESS_MM = (1.2, 2.0)
TOUCH_MM = 1.5
MAX_FACES = {'camera': 3000, 'camera_mount': 6000, 'electronics': 8000}


def known_surfaces():
    clouds = []
    for path in sorted((PACKAGE / 'meshes').glob('*.stl')):
        if path.stem in STATIC:
            continue  # what an earlier run of this tool wrote
        mesh = trimesh.load(path)  # millimetres
        samples, _ = trimesh.sample.sample_surface(mesh, int(min(max(mesh.area * 4, 2000), 1_500_000)))
        clouds += [samples, mesh.vertices]
    return cKDTree(np.vstack(clouds))


def touches(a, b):
    """Axis-aligned boxes closer than TOUCH_MM."""
    return bool(np.all(a.bounds[0] - TOUCH_MM <= b.bounds[1]) and np.all(b.bounds[0] - TOUCH_MM <= a.bounds[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('export', type=Path, help='the geometry export folder (has export_report.json)')
    export = parser.parse_args().export.expanduser()
    report = json.loads((export / 'export_report.json').read_text())
    to_mm = 1000.0 if report.get('units', 'metres').startswith('metre') else 1.0

    known = known_surfaces()
    new, seen, recognised = [], set(), 0
    for body in report['bodies']:
        mesh = trimesh.load(export / body['mesh'])
        mesh.apply_scale(to_mm)
        vertices = mesh.vertices[:: max(1, len(mesh.vertices) // 3000)]
        if (known.query(vertices)[0] < ON_SURFACE_MM).mean() >= KNOWN_SHARE:
            recognised += 1
            continue
        # "old_component" leftovers of earlier exports repeat bodies exactly
        key = tuple(np.round(mesh.bounds, 1).ravel())
        if key not in seen:
            seen.add(key)
            new.append(mesh)
    if recognised < 0.8 * len(report['bodies']):
        raise SystemExit(f'only {recognised} of {len(report["bodies"])} bodies lie on the known hand: a different '
                         f'frame or pose. Re-run cad_to_linkage.py on a named export first.')

    extents = [np.sort(mesh.extents)[::-1] for mesh in new]
    cameras = [m for m, e in zip(new, extents) if np.all(np.abs(e - D435_MM) < 4.0)]
    boards = [m for m, e in zip(new, extents) if PCB_THICKNESS_MM[0] <= e[2] <= PCB_THICKNESS_MM[1] and e[1] > 20.0]
    if len(cameras) != 1 or len(boards) != 1:
        raise SystemExit(f'expected one RealSense-sized body and one PCB, found {len(cameras)} and {len(boards)}')
    camera, board = cameras[0], boards[0]

    # The front glass: a thin plate lying on one of the camera's long faces
    glass = [m for m, e in zip(new, extents) if m is not camera and e[2] < 1.6 and abs(e[0] - extents[new.index(camera)][0]) < 12.0
             and touches(m, camera)]
    groups = {'camera': [camera] + glass, 'electronics': [board], 'camera_mount': []}
    rest = [m for m in new if m is not camera and m is not board and all(m is not g for g in glass)]
    grown = True
    while grown:  # connectors and standoffs touch the board, the carrier plate touches the standoffs
        grown = False
        for mesh in list(rest):
            if any(touches(mesh, member) for member in groups['electronics']):
                groups['electronics'].append(mesh)
                rest.remove(mesh)
                grown = True
    groups['camera_mount'] = rest  # everything else new is there to hold the camera

    for name, meshes in groups.items():
        merged = trimesh.util.concatenate(meshes)
        if len(merged.faces) > MAX_FACES[name]:
            merged = merged.simplify_quadric_decimation(face_count=MAX_FACES[name])
        merged.export(PACKAGE / 'meshes' / f'{name}.stl')

    # Where it looks: from the body's centre through the glass. Without a glass plate, along the
    # fingers (+Y), which is how the hand is built.
    centre = camera.bounds.mean(axis=0)
    forward = np.array([0.0, 1.0, 0.0])
    if glass:
        offset = glass[0].bounds.mean(axis=0) - centre
        forward = np.sign(offset) * (np.abs(offset) == np.abs(offset).max())
    long_axis = np.eye(3)[int(np.argmax(camera.extents))]
    front = centre + forward * (camera.extents @ np.abs(forward)) / 2.0
    static = {
        'camera': {
            'xyz': [round(float(v) / 1000.0, 4) for v in front],        # centre of the front face, metres
            'forward': [int(v) for v in forward],                       # base_link axis the lenses look along
            'long_axis': [int(v) for v in long_axis],                   # base_link axis the two imagers lie along
        },
        'parts': {name: len(meshes) for name, meshes in groups.items()},
    }
    header = ('# GENERATED by tools/cad_static_parts.py from a geometry-only Fusion export - do not edit.\n'
              '# Which way is "up" for the camera cannot be read off a box: `camera.rpy` in\n'
              '# hand_params.yaml says how camera_link is turned.\n')
    (PACKAGE / 'config' / 'static_parts.yaml').write_text(header + yaml.safe_dump(static, sort_keys=False))
    print(f'{recognised} bodies already known, {len(new)} new: ' + ', '.join(f'{k} = {len(v)}' for k, v in groups.items()))
    print(f'camera front face at {static["camera"]["xyz"]} m, looking along {static["camera"]["forward"]}, '
          f'imagers along {static["camera"]["long_axis"]}')


if __name__ == '__main__':
    main()
