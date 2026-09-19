import {
  Box3,
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
import URDFLoader, { type URDFJoint, type URDFRobot } from "urdf-loader"

import { FINGERS, JOINT_MAX_RAD, type Finger } from "@/lib/types"

import { PASSIVE_ROLES, passiveJointSolver, type PassiveAngles } from "./linkage"
import type { HandDescription } from "./use-urdf"

/** `solid` is the measured hand; `ghost` is the commanded pose drawn as a wireframe. */
export type HandVariant = "solid" | "ghost"

/** Every launch file roots the hand here; `world` and its mount exist in sim only. */
const HAND_ROOT_LINK = "base_link"

/** Layer for everything that must not end up in the contact-shadow pass (lines, the ghost). */
export const OVERLAY_LAYER = 1

/** The accent belongs to the commanded ghost alone; the measured hand is white, metal and graphite. */
const SIGNAL = "#f2490c"
const INK = "#242424"

/** Looks by URDF material name (`appearance` in hand_params.yaml names the parts, not these colours). */
const SURFACES: Record<string, ConstructorParameters<typeof MeshPhysicalMaterial>[0]> = {
  body: { color: "#2b2c2f", roughness: 0.55, metalness: 0.1 },
  servo: { color: "#3b3c41", roughness: 0.45, metalness: 0.2 },
  finger: { color: "#f4f4f2", roughness: 0.5, metalness: 0, clearcoat: 0.3, clearcoatRoughness: 0.6 },
  accent: { color: "#c4c6ca", roughness: 0.35, metalness: 0.65 },
  pad: { color: "#1c1c1e", roughness: 0.9, metalness: 0 },
  // The mannequin hand of the CAD: a quiet reference behind the machine, not part of it.
  wearer: { color: "#d9d6d1", roughness: 0.95, metalness: 0, transparent: true, opacity: 0.32, depthWrite: false },
}
/** Parts drawn as a backdrop: no edge lines, no shadow. */
const BACKDROP = new Set(["wearer"])
const FALLBACK_SURFACE = SURFACES.finger

/** Faces that meet at less than this stay one surface: CAD fillets must not become line hatching. */
const EDGE_ANGLE_DEG = 38
/** Gap between the ground and the lowest point of the hand, as a share of the hand's height. */
const GROUND_CLEARANCE_RATIO = 0.04

const GHOST_FILL_OPACITY = 0.05
const GHOST_EDGE_OPACITY = 0.7
const SOLID_EDGE_OPACITY = 0.16

export interface FingerRig {
  finger: Finger
  /** Position in the system-wide finger order. */
  index: number
  /** Travel of the driven joint (the servo horn) in radians for a curl of 1. */
  travel: number
  /** Poses the whole finger for a driven-joint angle: the horn, and the linkage that follows it. */
  setAngle: (angle: number) => void
  /** Empty object in the middle of the contact pad; labels anchor to it. */
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

/** Every part of a finger's linkage is a link called `<finger>_<part>`. */
function fingerOfLink(name: string): Finger | null {
  return FINGERS.find((finger) => name.startsWith(`${finger}_`)) ?? null
}

function owningLink(object: Object3D): string {
  for (let node: Object3D | null = object; node; node = node.parent) {
    if ("isURDFLink" in node) return (node as URDFRobot).urdfName
  }
  return ""
}

/**
 * Parses the URDF onto the CAD meshes and restyles it as a designed object: physically based
 * materials by part, thin edge lines (ink on the measured hand, the accent on the ghost).
 * `<gazebo>` / `<ros2_control>` tags are skipped by the parser. The meshes belong to the
 * description and are shared by both variants, so they are not disposed here.
 */
export function buildHandModel(description: HandDescription, variant: HandVariant): HandModel {
  const loader = new URDFLoader()
  // Keep `package://` paths as they are: they are the keys of `description.meshes`.
  loader.packages = (name: string) => `package://${name}`
  // The loader hands over the URDF material; its name says which part this is (see SURFACES).
  loader.loadMeshCb = (path, _manager, material, done) => {
    const geometry = description.meshes.get(path)
    if (geometry) done(new Mesh(geometry, material))
    else done(new Object3D(), new Error(`mesh not loaded: ${path}`))
  }
  const robot = loader.parse(description.xml)
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
  const baseEdges = edgeMaterial()
  const shared = new Map<string, Material>()
  const surface = (name: string) => {
    if (!shared.has(name)) shared.set(name, track(new MeshPhysicalMaterial(SURFACES[name] ?? FALLBACK_SURFACE)))
    return shared.get(name)!
  }
  const edgesOf = new Map<BufferGeometry, EdgesGeometry>()
  const edgeGeometry = (geometry: BufferGeometry) => {
    if (!edgesOf.has(geometry)) {
      const edges = new EdgesGeometry(geometry, EDGE_ANGLE_DEG)
      geometries.push(edges)
      edgesOf.set(geometry, edges)
    }
    return edgesOf.get(geometry)!
  }

  const parts: Mesh[] = []
  robot.traverse((object) => {
    if (object instanceof Mesh) parts.push(object)
  })

  const backdrop = new Set<Mesh>()
  const fingerMaterials = new Map<Finger, Material[]>()
  const fingerEdges = new Map<Finger, LineBasicMaterial>()
  const tips = new Map<Finger, Object3D>()
  for (const mesh of parts) {
    const link = owningLink(mesh)
    const finger = fingerOfLink(link)
    const look = (mesh.material as Material).name
    ;[mesh.material].flat().forEach((material) => material.dispose()) // the loader's placeholder

    const own: Material[] = []
    if (isGhost) {
      const fill = track(
        new MeshBasicMaterial({ color: SIGNAL, transparent: true, opacity: GHOST_FILL_OPACITY, depthWrite: false }),
      )
      own.push(fill)
      mesh.material = fill
      mesh.layers.set(OVERLAY_LAYER)
      mesh.renderOrder = 2
      // The base never moves, so a commanded copy of it would only add noise.
      mesh.visible = finger !== null
    } else {
      mesh.castShadow = !BACKDROP.has(look)
      mesh.receiveShadow = !BACKDROP.has(look)
      mesh.material = surface(look)
    }
    if (BACKDROP.has(look)) {
      mesh.renderOrder = 1 // after the opaque machine, which then shows through it
      if (isGhost) mesh.visible = false
      backdrop.add(mesh)
      continue
    }

    if (finger && !fingerEdges.has(finger)) {
      fingerEdges.set(finger, edgeMaterial())
      own.push(fingerEdges.get(finger)!)
    }
    const edges = new LineSegments(edgeGeometry(mesh.geometry), finger ? fingerEdges.get(finger)! : baseEdges)
    edges.layers.set(OVERLAY_LAYER)
    edges.renderOrder = 3
    edges.visible = mesh.visible
    mesh.add(edges)

    // The contact pad is where the wearer's finger sits: that is "the fingertip" of this hand.
    if (finger && link === `${finger}_finger` && look === "pad") {
      mesh.geometry.computeBoundingBox()
      const tip = new Object3D()
      mesh.geometry.boundingBox!.getCenter(tip.position) // mesh space (mm), scaled with the mesh
      mesh.add(tip)
      tips.set(finger, tip)
    }
    if (finger) fingerMaterials.set(finger, [...(fingerMaterials.get(finger) ?? []), ...own])
  }

  const fingers: FingerRig[] = []
  for (const finger of FINGERS) {
    const joint: URDFJoint | undefined = robot.joints[`${finger}_joint`]
    const tip = tips.get(finger)
    if (!joint || !tip) continue
    const upper = Number(joint.limit?.upper)
    const travel = upper > 0 ? upper : JOINT_MAX_RAD

    // The loops of the linkage close only if its passive joints follow the horn.
    const geometry = description.linkage?.[finger]
    const passive = PASSIVE_ROLES.map((role) => robot.joints[`${finger}_${role}_joint`])
    const solve = geometry && passive.every(Boolean) ? passiveJointSolver(geometry, travel) : null
    const angles: PassiveAngles = [0, 0, 0, 0, 0, 0]

    fingers.push({
      finger,
      index: FINGERS.indexOf(finger),
      travel,
      setAngle: (angle) => {
        joint.setJointValue(angle)
        if (!solve) return
        solve(angle, angles)
        for (let k = 0; k < passive.length; k++) passive[k].setJointValue(angles[k])
      },
      tip,
      materials: fingerMaterials.get(finger) ?? [],
    })
  }

  // Presented in its own `base_link` frame, which is the CAD frame: +Z is the back of the hand,
  // the fingers point along +Y and curl towards -Z. base_link +Z becomes three.js +Y, so the
  // hand hovers palm down. The sim bolts it to `world` through a mount, which must not show.
  // Turned about the vertical as well, so the fingers point at the default camera (+Z).
  const root = new Group()
  root.rotation.set(-Math.PI / 2, 0, Math.PI)
  root.add(robot.links[HAND_ROOT_LINK] ?? robot)

  // Frame on the hand itself (whatever the URDF root is), over its whole travel.
  const box = new Box3()
  for (const curl of [0, 1]) {
    fingers.forEach((rig) => rig.setAngle(rig.travel * curl))
    root.updateMatrixWorld(true)
    // The camera frames the machine; the mannequin's forearm would push it into a corner.
    parts.forEach((mesh) => backdrop.has(mesh) || box.expandByObject(mesh))
  }
  fingers.forEach((rig) => rig.setAngle(0))

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
