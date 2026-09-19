"""The URDF is a tree and the real linkage has loops: they close only if the passive joint
angles from htn_control.linkage are right. Checked here on the generated URDF itself."""
import math
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest
import yaml

from htn_control.hand_config import FINGERS
from htn_control.linkage import PASSIVE, Linkage, PassiveJoints

DESCRIPTION = Path(__file__).resolve().parents[2] / 'htn_description'
LINKAGE = yaml.safe_load((DESCRIPTION / 'config' / 'linkage.yaml').read_text())['fingers']
PARAMS = yaml.safe_load((DESCRIPTION / 'config' / 'hand_params.yaml').read_text())
# Each loop closes where two parts share a pin: (pivot, link A, the pivot A hangs on, link B, B's)
LOOPS = [('A', 'rod', 'P', 'triangle', 'G1'), ('M', 'ternary', 'B', 'long', 'G2'), ('U', 'binary', 'T', 'finger', 'E')]


@pytest.fixture(scope='module')
def urdf():
    xml = subprocess.run(
        ['xacro', str(DESCRIPTION / 'urdf' / 'hand.urdf.xacro'),
         f'params_file:={DESCRIPTION / "config" / "hand_params.yaml"}',
         f'linkage_file:={DESCRIPTION / "config" / "linkage.yaml"}',
         f'static_file:={DESCRIPTION / "config" / "static_parts.yaml"}'],
        check=True, capture_output=True, text=True).stdout
    return ET.fromstring(xml)


def rotation(axis, angle):
    x, y, z = axis
    c, s, v = math.cos(angle), math.sin(angle), 1 - math.cos(angle)
    return np.array([[c + x*x*v, x*y*v - z*s, x*z*v + y*s],
                     [y*x*v + z*s, c + y*y*v, y*z*v - x*s],
                     [z*x*v - y*s, z*y*v + x*s, c + z*z*v]])


def link_poses(urdf, angles):
    """link -> (R, t) in base_link for the given joint angles (origins here have no rpy)."""
    joints = {j.find('child').get('link'): j for j in urdf.findall('joint')}
    poses = {'base_link': (np.eye(3), np.zeros(3))}

    def pose(link):
        if link not in poses:
            joint = joints[link]
            R, t = pose(joint.find('parent').get('link'))
            origin = np.array([float(v) for v in joint.find('origin').get('xyz').split()])
            axis = joint.find('axis')  # fixed joints have none (and nothing hangs on them here)
            axis = [float(v) for v in axis.get('xyz').split()] if axis is not None else (1.0, 0.0, 0.0)
            poses[link] = (R @ rotation(axis, angles.get(joint.get('name'), 0.0)), t + R @ origin)
        return poses[link]

    for link in joints:
        pose(link)
    return poses


def in_3d(finger, point, origin):
    """Pivot `point` relative to pivot `origin`, metres, in the (unrotated) frame of a link at `origin`."""
    l = LINKAGE[finger]
    du, dv = (np.array(l['pivots'][point]) - np.array(l['pivots'][origin])) / 1000.0
    return np.array([0.0, du, dv]) if l['axis'] == 'x' else np.array([du, dv, 0.0])


def test_contract_joints_and_links(urdf):
    names = {j.get('name') for j in urdf.findall('joint')}
    links = {l.get('name') for l in urdf.findall('link')}
    for finger in FINGERS:
        assert f'{finger}_joint' in names and f'{finger}_finger' in links
        assert {f'{finger}_{role}_joint' for role in PASSIVE} <= names
    driven = [j for j in urdf.findall('joint') if j.get('type') == 'revolute']
    assert sorted(j.get('name') for j in driven) == sorted(f'{f}_joint' for f in FINGERS)


@pytest.mark.parametrize('finger', FINGERS)
@pytest.mark.parametrize('fraction', [0.0, 0.1, 0.5, 0.9, 1.0])
def test_the_three_loops_close(urdf, finger, fraction):
    l, closed = LINKAGE[finger], PARAMS['fingers'][finger]['max_angle']
    q = closed * fraction
    passive = PassiveJoints(Linkage(l['pivots'], l['closing']), closed)(q)
    angles = {f'{finger}_joint': q, **{f'{finger}_{role}_joint': a for role, a in zip(PASSIVE, passive)}}
    poses = link_poses(urdf, angles)
    for pivot, link_a, hangs_a, link_b, hangs_b in LOOPS:
        (Ra, ta), (Rb, tb) = poses[f'{finger}_{link_a}'], poses[f'{finger}_{link_b}']
        gap = np.linalg.norm((ta + Ra @ in_3d(finger, pivot, hangs_a)) - (tb + Rb @ in_3d(finger, pivot, hangs_b)))
        assert gap < 5e-5, f'{finger} loop at {pivot} is open by {gap * 1000:.3f} mm at q = {q:.2f}'


@pytest.mark.parametrize('finger', FINGERS)
def test_closed_is_a_90_degree_curl_with_margin_before_the_linkage_binds(finger):
    l, closed = LINKAGE[finger], PARAMS['fingers'][finger]['max_angle']
    solution = Linkage(l['pivots'], l['closing']).sweep()
    at_closed = min(solution, key=lambda s: abs(abs(s['horn']) - closed))
    assert abs(math.degrees(at_closed['curl'])) == pytest.approx(90.0, abs=1.0)
    assert closed < l['lock_rad'] - math.radians(10.0)


def test_the_camera_frame_hangs_on_the_hand_and_looks_along_the_fingers(urdf):
    joint = next(j for j in urdf.findall('joint') if j.find('child').get('link') == 'camera_link')
    assert joint.get('type') == 'fixed' and joint.find('parent').get('link') == 'base_link'
    roll, pitch, yaw = (float(v) for v in joint.find('origin').get('rpy').split())
    forward = (rotation((0, 0, 1), yaw) @ rotation((0, 1, 0), pitch) @ rotation((1, 0, 0), roll))[:, 0]
    assert forward == pytest.approx([0.0, 1.0, 0.0], abs=1e-3)  # camera x = base +Y, towards the fingertips


def test_open_is_the_cad_pose():
    for finger in FINGERS:
        l = LINKAGE[finger]
        assert PassiveJoints(Linkage(l['pivots'], l['closing']), 1.0)(0.0) == pytest.approx((0.0,) * 6, abs=1e-9)
