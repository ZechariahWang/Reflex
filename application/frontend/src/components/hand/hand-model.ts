import {
  Box3,
  BoxGeometry,
  EdgesGeometry,
  Group,
  LineBasicMaterial,
  LineSegments,
  Mesh,
  MeshBasicMaterial,
  MeshPhysicalMaterial,
  Object3D,
  Sphere,
  Vector3,
  type BufferGeometry,
  type Material,
} from "three"
import { RoundedBoxGeometry } from "three/examples/jsm/geometries/RoundedBoxGeometry.js"
import URDFLoader, { type URDFJoint, type URDFRobot } from "urdf-loader"

import { FINGERS, JOINT_MAX_RAD, type Finger } from "@/lib/types"

/** `solid` is the measured hand; `ghost` is the commanded pose drawn as a wireframe. */
export type HandVariant = "solid" | "ghost"

/** Every launch file roots the hand here; `world` and its mount exist in sim only. */
const HAND_ROOT_LINK = "base_link"

/** Layer for everything that must not end up in the contact-shadow pass (lines, the ghost). */
export const OVERLAY_LAYER = 1

/** The accent belongs to the commanded ghost alone; the measured hand is white and graphite. */
const SIGNAL = "#f2490c"
const INK = "#242424"
const CERAMIC = "#f4f4f2"
const GRAPHITE = "#2b2c2f"

/** Corner radius as a share of a box's thinnest side. */
const BEVEL_RATIO = 0.14
/** Edge lines sit on the bevel's arc rather than on the sharp corner it replaced. */
const EDGE_INSET_RATIO = 0.25
/** Gap between the ground and the palm resting over it, as a share of the hand's height. */
const GROUND_CLEARANCE_RATIO = 0.04

const GHOST_FILL_OPACITY = 0.05
const GHOST_EDGE_OPACITY = 0.85
const SOLID_EDGE_OPACITY = 0.18

export interface FingerRig {
  finger: Finger
  /** Position in the system-wide finger order. */
  index: number
  joint: URDFJoint
  /** Joint travel in radians for a curl of 1. */
  travel: number
  /** Empty object at the far end of the finger link; labels anchor to it. */
  tip: Object3D
  /** Per-finger materials, so each ghost finger can fade on its own. */
  materials: Material[]
}

export interface HandModel {
  /** Y-up wrapper, positioned so the ground is y = 0 and the hand is centred over the origin. */
  root: Group
  fingers: FingerRig[]
  /** Bounds over the whole joint travel, in world space. */
  bounds: Sphere
  /** Highest point of the hand above the ground. */
  top: number
  /** Ghost only: 0 hides a finger, 1 draws it fully. */
  setPresence: (rig: FingerRig, amount: number) => void
  setVisible: (visible: boolean) => void
  dispose: () => void
}

function fingerOfLink(name: string): Finger | null {
  return FINGERS.find((finger) => name === `${finger}_finger`) ?? null
}

function owningLink(object: Object3D): string {
  for (let node: Object3D | null = object; node; node = node.parent) {
    if ("isURDFLink" in node) return (node as URDFRobot).urdfName
  }
  return ""
}

/** The end of a finger link: its visual's centre pushed out to the far face, in link space. */
function tipPosition(visualMesh: Mesh, size: Vector3, link: Object3D): Vector3 {
  link.updateWorldMatrix(true, true)
  const centre = link.worldToLocal(visualMesh.getWorldPosition(new Vector3()))
  if (centre.lengthSq() === 0) return centre
  const direction = centre.clone().normalize()
  const halfExtent = Math.abs(direction.x) * size.x + Math.abs(direction.y) * size.y + Math.abs(direction.z) * size.z
  return centre.addScaledVector(direction, halfExtent / 2)
}

/**
 * Parses the URDF and restyles it as a designed object: bevelled boxes sized from
 * the URDF geometry, physically based materials and thin edge lines (ink on the
 * measured hand, the accent on the ghost).
 * `<gazebo>` / `<ros2_control>` tags are skipped by the parser.
 */
export function buildHandModel(urdf: string, variant: HandVariant): HandModel {
  const robot = new URDFLoader().parse(urdf)
  const isGhost = variant === "ghost"
  const geometries: BufferGeometry[] = []
  const materials: Material[] = []

  const track = <T extends Material>(material: T): T => {
    materials.push(material)
    return material
  }

  const edgeMaterial = () =>
    track(
      new LineBasicMaterial({
        color: isGhost ? SIGNAL : INK,
        transparent: true,
        opacity: isGhost ? GHOST_EDGE_OPACITY : SOLID_EDGE_OPACITY,
        depthWrite: false,
      }),
    )
  const palmEdges = edgeMaterial()
  const graphite = isGhost
    ? null
    : track(
        new MeshPhysicalMaterial({
          color: GRAPHITE,
          roughness: 0.5,
          metalness: 0.1,
        }),
      )

  const fingerMaterials = new Map<Finger, Material[]>()
  const tips = new Map<Finger, Object3D>()
  const boxes: Mesh[] = []
  robot.traverse((object) => {
    if (object instanceof Mesh && object.geometry instanceof BoxGeometry) boxes.push(object)
  })

  for (const mesh of boxes) {
    const finger = fingerOfLink(owningLink(mesh))
    const size = mesh.scale.clone()
    const radius = Math.min(size.x, size.y, size.z) * BEVEL_RATIO

    const stale = [mesh.geometry, mesh.material].flat()
    stale.forEach((resource) => resource.dispose())

    mesh.scale.setScalar(1)
    mesh.geometry = new RoundedBoxGeometry(size.x, size.y, size.z, 3, radius)
    geometries.push(mesh.geometry)

    const own: Material[] = []
    if (isGhost) {
      const fill = track(
        new MeshBasicMaterial({ color: SIGNAL, transparent: true, opacity: GHOST_FILL_OPACITY, depthWrite: false }),
      )
      own.push(fill)
      mesh.material = fill
      mesh.layers.set(OVERLAY_LAYER)
      mesh.renderOrder = 2
      // The palm never moves, so a commanded copy of it would only add noise.
      mesh.visible = finger !== null
    } else {
      mesh.castShadow = true
      mesh.receiveShadow = true
      if (finger) {
        const surface = track(
          new MeshPhysicalMaterial({
            color: CERAMIC,
            roughness: 0.5,
            metalness: 0,
            clearcoat: 0.3,
            clearcoatRoughness: 0.6,
          }),
        )
        own.push(surface)
        mesh.material = surface
      } else {
        mesh.material = graphite!
      }
    }

    const inset = radius * EDGE_INSET_RATIO * 2
    const outline = new BoxGeometry(size.x - inset, size.y - inset, size.z - inset)
    const edgeGeometry = new EdgesGeometry(outline)
    outline.dispose()
    geometries.push(edgeGeometry)
    const edges = new LineSegments(edgeGeometry, finger ? edgeMaterial() : palmEdges)
    if (finger) own.push(edges.material)
    edges.layers.set(OVERLAY_LAYER)
    edges.renderOrder = 3
    edges.visible = mesh.visible
    mesh.add(edges)

    if (finger && !tips.has(finger)) {
      const link = robot.links[`${finger}_finger`]
      const tip = new Object3D()
      tip.position.copy(tipPosition(mesh, size, link))
      link.add(tip)
      tips.set(finger, tip)
    }
    if (finger) fingerMaterials.set(finger, [...(fingerMaterials.get(finger) ?? []), ...own])
  }

  const fingers: FingerRig[] = []
  for (const finger of FINGERS) {
    const joint = robot.joints[`${finger}_joint`]
    const tip = tips.get(finger)
    if (!joint || !tip) continue
    const upper = Number(joint.limit?.upper)
    fingers.push({
      finger,
      index: FINGERS.indexOf(finger),
      joint,
      travel: upper > 0 ? upper : JOINT_MAX_RAD,
      tip,
      materials: fingerMaterials.get(finger) ?? [],
    })
  }

  // Presented in its own `base_link` frame, palm resting over the ground and the open fingers
  // standing up: base_link -Z (the way fingers hang) becomes three.js +Y. The sim bolts the hand
  // to `world` through a rotated mount, which must not change how it is presented.
  const root = new Group()
  root.rotation.x = Math.PI / 2
  root.add(robot.links[HAND_ROOT_LINK] ?? robot)

  // Frame on the hand itself (whatever the URDF root is), over its whole travel.
  const box = new Box3()
  for (const curl of [0, 1]) {
    fingers.forEach((rig) => rig.joint.setJointValue(rig.travel * curl))
    root.updateMatrixWorld(true)
    boxes.forEach((mesh) => box.expandByObject(mesh))
  }
  fingers.forEach((rig) => rig.joint.setJointValue(0))

  const size = box.getSize(new Vector3())
  const centre = box.getCenter(new Vector3())
  const clearance = size.y * GROUND_CLEARANCE_RATIO
  root.position.set(-centre.x, clearance - box.min.y, -centre.z)
  root.updateMatrixWorld(true)
  box.translate(root.position)

  return {
    root,
    fingers,
    bounds: box.getBoundingSphere(new Sphere()),
    top: box.max.y,
    setPresence: (rig, amount) => {
      for (const material of rig.materials) {
        material.opacity = (material instanceof LineBasicMaterial ? GHOST_EDGE_OPACITY : GHOST_FILL_OPACITY) * amount
      }
    },
    setVisible: (visible) => {
      root.visible = visible
    },
    dispose: () => {
      geometries.forEach((geometry) => geometry.dispose())
      materials.forEach((material) => material.dispose())
    },
  }
}
