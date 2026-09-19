"use client"

import { useEffect, useMemo, useRef } from "react"
import { createPortal, useFrame } from "@react-three/fiber"
import {
  BoxGeometry,
  BufferGeometry,
  Color,
  EdgesGeometry,
  Float32BufferAttribute,
  Group,
  Line,
  LineBasicMaterial,
  LineLoop,
  LineSegments,
  Mesh,
  MeshBasicMaterial,
  RingGeometry,
  Vector3,
  type Object3D,
} from "three"

import { selectObjectIds, useSimStore } from "@/lib/sim-store"
import type { TrackedObject } from "@/lib/types"

import type { HudRefs } from "./hand-hud"
import { OVERLAY_LAYER, type HandModel } from "./hand-model"

/** Ground rings around the hand, metres; the radar draws the same ones. */
export const RANGE_RINGS_M = [0.25, 0.5, 1.0] as const
/** Radius of the radar's outer ring, metres: objects beyond it sit on its edge. */
export const RADAR_RANGE_M = 1.0
/** Radius of the radar's outer ring, SVG units (its viewBox is -50..50). */
export const RADAR_RADIUS = 44

/** An object counts as in view for this long after its last detection. */
const SEEN_S = 0.6
/** Age at which a remembered object has faded to its floor; the backend forgets it at about this point. */
const FADE_S = 12
const PRESENCE_FLOOR = 0.18
/** 1/s. A track update arrives at 10 Hz; the mark glides to it rather than stepping. */
const GLIDE_RATE = 9
const MAX_FRAME_DT = 1 / 20
/** How often the chip text (distance, age) is rewritten, per second. */
const TEXT_RATE = 8
const RING_SEGMENTS = 128
const RING_TICKS = 24

const INK = new Color("#242424")
const INK_MUTE = new Color("#727272")
const RING_COLOR = "#b9b9b9"
const TICK_COLOR = "#9a9a9a"
const BOX_OPACITY = 0.7
const DROP_OPACITY = 0.4
const FOOT_OPACITY = 0.55

/** Shared unit box outline, scaled per object. */
let unitEdges: EdgesGeometry | null = null
function edges(): EdgesGeometry {
  return (unitEdges ??= new EdgesGeometry(new BoxGeometry(1, 1, 1)))
}

function damp(rate: number, dt: number): number {
  return 1 - Math.exp(-rate * dt)
}

/** 1 while in view, easing to PRESENCE_FLOOR over the memory span. */
function presenceOf(age: number): number {
  if (age <= SEEN_S) return 1
  const fade = Math.min(1, (age - SEEN_S) / (FADE_S - SEEN_S))
  return 1 - (1 - PRESENCE_FLOOR) * fade * (2 - fade)
}

function circle(radius: number, segments: number): BufferGeometry {
  const points: number[] = []
  for (let i = 0; i < segments; i++) {
    const a = (i / segments) * Math.PI * 2
    points.push(Math.cos(a) * radius, 0, Math.sin(a) * radius)
  }
  return new BufferGeometry().setAttribute("position", new Float32BufferAttribute(points, 3))
}

function ticks(radius: number, count: number, length: number): BufferGeometry {
  const points: number[] = []
  for (let i = 0; i < count; i++) {
    const a = (i / count) * Math.PI * 2
    const major = i % (count / 4) === 0
    const inner = radius - (major ? length * 2 : length)
    points.push(Math.cos(a) * inner, 0, Math.sin(a) * inner, Math.cos(a) * radius, 0, Math.sin(a) * radius)
  }
  return new BufferGeometry().setAttribute("position", new Float32BufferAttribute(points, 3))
}

/** The rings and ticks on the ground, built once. */
class RingParts {
  readonly group = new Group()
  private readonly disposables: { dispose: () => void }[] = []

  constructor() {
    const ringMaterial = new LineBasicMaterial({ color: RING_COLOR, transparent: true, opacity: 0.8, depthWrite: false })
    const tickMaterial = new LineBasicMaterial({ color: TICK_COLOR, transparent: true, opacity: 0.9, depthWrite: false })
    const rings = RANGE_RINGS_M.map((radius) => new LineLoop(circle(radius, RING_SEGMENTS), ringMaterial))
    const outer = RANGE_RINGS_M[RANGE_RINGS_M.length - 1]
    const marks = new LineSegments(ticks(outer, RING_TICKS, 0.012), tickMaterial)
    this.group.position.y = 0.0008
    this.group.add(...rings, marks)
    this.group.traverse((node) => node.layers.set(OVERLAY_LAYER))
    this.disposables.push(ringMaterial, tickMaterial, marks.geometry, ...rings.map((ring) => ring.geometry))
  }

  dispose(): void {
    this.disposables.forEach((item) => item.dispose())
  }
}

/** Concentric range rings on the ground, centred on the hand: the scale of the map. */
export function RangeRings() {
  const parts = useMemo(() => new RingParts(), [])
  useEffect(() => () => parts.dispose(), [parts])
  return <primitive object={parts.group} />
}

/**
 * The three.js pieces of one object: its outline box (placed in the camera's frame), the drop
 * line to the ground and the footprint ring (placed in the world). Methods, so the frame loop
 * never assigns into React-owned state.
 */
class MarkParts {
  readonly box: LineSegments
  readonly drop: Line
  readonly foot: Mesh
  private readonly boxMaterial = new LineBasicMaterial({ color: INK, transparent: true, opacity: BOX_OPACITY, depthWrite: false })
  private readonly dropMaterial = new LineBasicMaterial({ color: INK_MUTE, transparent: true, opacity: DROP_OPACITY, depthWrite: false })
  private readonly footMaterial = new MeshBasicMaterial({ color: INK, transparent: true, opacity: FOOT_OPACITY, depthWrite: false })
  private readonly dropGeometry = new BufferGeometry().setAttribute("position", new Float32BufferAttribute([0, 0, 0, 0, 0, 0], 3))
  private readonly footGeometry = new RingGeometry(0.008, 0.011, 40)

  constructor() {
    this.box = new LineSegments(edges(), this.boxMaterial)
    this.box.renderOrder = 3
    this.drop = new Line(this.dropGeometry, this.dropMaterial)
    this.foot = new Mesh(this.footGeometry, this.footMaterial)
    this.foot.rotation.x = -Math.PI / 2
    for (const object of [this.box, this.drop, this.foot]) object.layers.set(OVERLAY_LAYER)
  }

  /** Box pose in the camera's frame. */
  place(position: Vector3, size: Vector3): void {
    this.box.position.copy(position)
    this.box.scale.copy(size)
  }

  /** In view: ink at full presence. Remembered: muted, fading with age. */
  setPresence(seen: boolean, presence: number): void {
    this.boxMaterial.color.copy(seen ? INK : INK_MUTE)
    this.boxMaterial.opacity = BOX_OPACITY * presence
    this.dropMaterial.opacity = DROP_OPACITY * presence
    this.footMaterial.opacity = FOOT_OPACITY * presence
  }

  /** Drop line and ring under the box's world position. */
  setFootprint(world: Vector3): void {
    const positions = this.dropGeometry.getAttribute("position")
    positions.setXYZ(0, world.x, world.y, world.z)
    positions.setXYZ(1, world.x, 0.001, world.z)
    positions.needsUpdate = true
    this.foot.position.set(world.x, 0.001, world.z)
  }

  dispose(): void {
    for (const item of [this.boxMaterial, this.dropMaterial, this.footMaterial, this.dropGeometry, this.footGeometry]) item.dispose()
  }
}

interface MarkProps {
  id: number
  /** `camera_link` of the measured hand: the frame the backend places objects in. */
  anchor: Object3D
  hud: HudRefs
}

/** DOM pieces of one object, looked up once per mark. */
interface MarkNodes {
  chip: HTMLElement
  dot: HTMLElement
  distance: HTMLElement
  age: HTMLElement
  bar: HTMLElement
  radar: SVGGElement | null
}

function resolveNodes(hud: HudRefs, id: number): MarkNodes | null {
  const labels = hud.objects.current
  if (!labels) return null
  const chip = labels.querySelector<HTMLElement>(`[data-object="${id}"][data-part="chip"]`)
  const dot = labels.querySelector<HTMLElement>(`[data-object="${id}"][data-part="dot"]`)
  if (!chip || !dot) return null
  return {
    chip,
    dot,
    distance: chip.querySelector<HTMLElement>("[data-distance]")!,
    age: chip.querySelector<HTMLElement>("[data-age]")!,
    bar: chip.querySelector<HTMLElement>("[data-bar]")!,
    radar: hud.radar.current?.querySelector<SVGGElement>(`[data-object="${id}"]`) ?? null,
  }
}

/**
 * One tracked object: an outline box in the camera's frame, a drop line and footprint on the
 * ground, its label chip in the HUD and its dot on the radar. Everything moves through refs
 * inside the frame loop; React only mounts and unmounts the mark.
 */
function ObjectMark({ id, anchor, hud }: MarkProps) {
  const parts = useMemo(() => new MarkParts(), [])
  useEffect(() => () => parts.dispose(), [parts])

  const nodes = useRef<MarkNodes | null>(null)
  const state = useRef({
    placed: false,
    position: new Vector3(),
    size: new Vector3(1, 1, 1),
    presence: 1,
    world: new Vector3(),
    screen: new Vector3(),
    textAt: 0,
    text: "",
  })

  useFrame(({ camera, size: viewport }, rawDt) => {
    const dt = Math.min(rawDt, MAX_FRAME_DT)
    const track = useSimStore.getState().live.message?.objects.find((o) => o.id === id)
    const mark = state.current
    if (!track) return

    // Glide to the track; the first sample places the mark outright.
    const k = mark.placed ? damp(GLIDE_RATE, dt) : 1
    mark.placed = true
    mark.position.x += (track.xyz[0] - mark.position.x) * k
    mark.position.y += (track.xyz[1] - mark.position.y) * k
    mark.position.z += (track.xyz[2] - mark.position.z) * k
    mark.size.x += (Math.max(0.01, track.size[0]) - mark.size.x) * k
    mark.size.y += (Math.max(0.01, track.size[1]) - mark.size.y) * k
    mark.size.z += (Math.max(0.01, track.size[2]) - mark.size.z) * k
    parts.place(mark.position, mark.size)

    const seen = track.age <= SEEN_S
    mark.presence += (presenceOf(track.age) - mark.presence) * damp(GLIDE_RATE, dt)
    parts.setPresence(seen, mark.presence)

    parts.box.getWorldPosition(mark.world)
    parts.setFootprint(mark.world)

    nodes.current ??= resolveNodes(hud, id)
    const dom = nodes.current
    if (!dom) return

    // The chip hangs off the top of the box.
    mark.screen.set(mark.world.x, mark.world.y + mark.size.z * 0.5 + 0.01, mark.world.z).project(camera)
    const shown = mark.screen.z < 1
    const x = (mark.screen.x * 0.5 + 0.5) * viewport.width
    const y = (-mark.screen.y * 0.5 + 0.5) * viewport.height
    const opacity = shown ? mark.presence.toFixed(3) : "0"
    const seenFlag = seen ? "1" : "0"
    dom.dot.style.transform = `translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, 0)`
    dom.dot.style.opacity = opacity
    dom.dot.dataset.seen = seenFlag
    dom.chip.style.transform = `translate3d(${(x + 10).toFixed(1)}px, ${(y - 26).toFixed(1)}px, 0)`
    dom.chip.style.opacity = opacity
    dom.chip.dataset.seen = seenFlag

    if (dom.radar) {
      // Top-down, fingers up the screen: three.js +Z is radar "north", +X is to the left.
      const range = Math.hypot(mark.world.x, mark.world.z)
      const clamp = range > RADAR_RANGE_M ? RADAR_RANGE_M / range : 1
      const scale = (RADAR_RADIUS / RADAR_RANGE_M) * clamp
      dom.radar.setAttribute("transform", `translate(${(-mark.world.x * scale).toFixed(2)} ${(-mark.world.z * scale).toFixed(2)})`)
      dom.radar.setAttribute("opacity", opacity)
      dom.radar.dataset.seen = seenFlag
    }

    const now = performance.now()
    if (now - mark.textAt < 1000 / TEXT_RATE) return
    mark.textAt = now
    const distance = Math.hypot(track.xyz[0], track.xyz[1], track.xyz[2])
    const text = `${distance.toFixed(2)} m|${seen ? "in view" : `${Math.round(track.age)} s ago`}`
    if (text !== mark.text) {
      mark.text = text
      const [range, when] = text.split("|")
      dom.distance.textContent = range
      dom.age.textContent = when
    }
    dom.bar.style.transform = `scaleX(${mark.presence.toFixed(3)})`
  })

  return (
    <>
      {createPortal(<primitive object={parts.box} />, anchor)}
      <primitive object={parts.drop} />
      <primitive object={parts.foot} />
    </>
  )
}

/** The surroundings: range rings on the ground and a mark for every object the backend tracks. */
export function WorldLayer({ model, hud }: { model: HandModel; hud: HudRefs }) {
  const ids = useSimStore(selectObjectIds)
  const anchor = model.cameraLink
  const list = useMemo(() => (ids ? ids.split(",").map(Number) : []), [ids])

  return (
    <>
      <RangeRings />
      {anchor && list.map((id) => <ObjectMark key={id} id={id} anchor={anchor} hud={hud} />)}
    </>
  )
}

/** For the HUD: the same short form of an object's label everywhere. */
export function shortLabel(object: Pick<TrackedObject, "label">): string {
  return object.label.replace(/^cell /, "").toUpperCase()
}
