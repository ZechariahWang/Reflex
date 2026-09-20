"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { Canvas, useFrame, useThree } from "@react-three/fiber"
import { ContactShadows, Environment, Lightformer, OrbitControls } from "@react-three/drei"
import { MathUtils, NeutralToneMapping, Quaternion, Spherical, Vector3 } from "three"
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib"

import { useSimStore } from "@/lib/sim-store"
import { FINGERS } from "@/lib/types"

import { LABEL_LAYOUT, resolveHud, type HudNodes, type HudRefs } from "./hand-hud"
import { OVERLAY_LAYER, buildHandModel, type HandModel } from "./hand-model"
import type { HandDescription } from "./use-urdf"
import { VIEW_ANGLES, allowsAutoOrbit, type ViewPreset } from "./views"
import { WorldLayer } from "./world-layer"

const PAGE = "#f6f6f6"
const FOV_DEG = 28
/** Breathing room around the hand's bounding sphere, which already spans the whole joint travel. */
const FIT_MARGIN = 1.02
/** 1/s. Smooths 60 Hz samples over ~22 ms: enough to hide a late packet, too little to feel as lag. */
const FOLLOW_RATE = 45
const GHOST_FADE_RATE = 9
/** Share of the ghost that stays drawn once the measured finger sits on its command. */
const GHOST_SETTLED = 0.15
/** Command/state gap (0..1 curl) at which the ghost is fully drawn. */
const GHOST_FULL_AT = 0.06
const VIEW_RATE = 4.5
const VIEW_DONE = 1e-3
/** Farthest the user may pull back, as a multiple of the hand-only fit: room for the map around it. */
const MAX_ZOOM_OUT = 9
const AUTO_ORBIT_RESUME_MS = 3500
/** rad/s. One idle lap takes a little under two minutes. */
const ORBIT_SPEED = ((Math.PI * 2) / 60) * 0.55
/** 1/s. The idle orbit eases in and out instead of snapping to speed. */
const ORBIT_EASE_RATE = 1.6
/** s. A frame longer than this (tab switch, GC pause) advances motion by this much at most. */
const MAX_FRAME_DT = 1 / 20
/** rad. Joint motion below this per frame counts as standing still. */
const STILL_EPSILON = 1e-4
/** s of stillness before the shadow passes are parked. */
const STILL_AFTER = 0.4
const GIZMO_AXIS_PX = 20
const GIZMO_LABEL_PX = 28

const LABEL_RATE = 12

/** base_link axes in the Y-up world, matching the model root's rotation: +Z (the back of the hand) is shown as up. */
const ROS_AXES = { x: new Vector3(-1, 0, 0), y: new Vector3(0, 0, 1), z: new Vector3(0, 1, 0) } as const

export interface HandSceneProps {
  description: HandDescription
  view: ViewPreset | null
  ghost: boolean
  reducedMotion: boolean
  hud: HudRefs
  /** The user took over the camera, so no preset applies any more. */
  onFreeLook: () => void
}

function fitDistance(radius: number, aspect: number): number {
  const vertical = MathUtils.degToRad(FOV_DEG) / 2
  const horizontal = Math.atan(Math.tan(vertical) * aspect)
  return (radius / Math.sin(Math.min(vertical, horizontal))) * FIT_MARGIN
}

function damp(rate: number, dt: number): number {
  return 1 - Math.exp(-rate * dt)
}

/** Softbox studio built from Lightformers: no HDRI download, rendered once. */
function Studio({ model, moving }: { model: HandModel; moving: boolean }) {
  const { radius } = model.bounds
  const extent = radius * 2.4

  return (
    <>
      <color attach="background" args={[PAGE]} />
      <Environment resolution={256} frames={1} environmentIntensity={0.8}>
        <color attach="background" args={["#e6e6e6"]} />
        <Lightformer form="rect" intensity={3.2} position={[0, 5, 0]} scale={[7, 7, 1]} target={[0, 0, 0]} />
        <Lightformer form="rect" intensity={2.4} position={[-5, 2, 3]} scale={[6, 3, 1]} target={[0, 0, 0]} />
        <Lightformer form="rect" intensity={1.4} position={[5, 1.5, -3]} scale={[6, 3, 1]} target={[0, 0, 0]} />
        <Lightformer form="ring" intensity={1.8} position={[2, 3, 5]} scale={2.5} target={[0, 0, 0]} />
      </Environment>

      <hemisphereLight args={["#ffffff", "#d8d8d8", 0.25]} />
      <directionalLight
        castShadow
        intensity={1.15}
        position={[radius * 3, radius * 7, radius * 4]}
        shadow-mapSize={[1024, 1024]}
        shadow-bias={-0.0004}
        shadow-normalBias={0.002}
        shadow-radius={5}
      >
        <orthographicCamera attach="shadow-camera" args={[-extent, extent, extent, -extent, radius * 0.1, radius * 20]} />
      </directionalLight>

      <ContactShadows
        position={[0, 0, 0]}
        scale={radius * 4}
        far={model.top}
        // The orbit never changes this shadow, only the fingers do: while the hand is still it is
        // drawn once and kept, rather than re-rendered and re-blurred every frame.
        frames={moving ? Number.POSITIVE_INFINITY : 1}
        resolution={512}
        blur={1.6}
        opacity={0.55}
        color="#242424"
      />
      {/* No ground grid: the contact shadow and the range rings are all the floor needs. */}
    </>
  )
}

interface HandProps {
  solid: HandModel
  ghost: HandModel
  ghostEnabled: boolean
  hud: HudRefs
  /** Fired when the fingers start or stop moving, never per frame. */
  onMovingChange: (moving: boolean) => void
}

/** Measured hand, commanded ghost, and the fingertip labels that follow the measured tips. */
function Hand({ solid, ghost, ghostEnabled, hud, onMovingChange }: HandProps) {
  const pose = useRef({
    angles: new Float32Array(FINGERS.length),
    curls: new Float32Array(FINGERS.length),
    ghostAngles: new Float32Array(FINGERS.length),
    presence: 0,
  })
  // Starts as moving, so the first frames draw their shadows.
  const motion = useRef({ moving: true, stillFor: 0 })

  // A new model needs its shadows drawn even if no finger is moving.
  useEffect(() => {
    motion.current.moving = true
    motion.current.stillFor = 0
    onMovingChange(true)
  }, [solid, onMovingChange])
  const nodes = useRef<HudNodes | null>(null)
  const projected = useRef(new Vector3())
  const callouts = useRef({
    tips: FINGERS.map(() => ({ x: 0, y: 0, shown: false })),
    order: FINGERS.map((_, i) => i),
    rows: new Float32Array(FINGERS.length).fill(Number.NaN),
  })

  useFrame(({ camera, size, gl }, rawDt) => {
    const dt = Math.min(rawDt, MAX_FRAME_DT)
    const message = useSimStore.getState().live.message
    const { angles, curls, ghostAngles } = pose.current
    const follow = damp(FOLLOW_RATE, dt)

    let moved = 0
    for (const rig of solid.fingers) {
      const i = rig.index
      const angle = message?.joints[`${rig.finger}_joint`] ?? 0
      const curl = message?.state[i] ?? 0
      const step = (angle - angles[i]) * follow
      moved = Math.max(moved, Math.abs(step))
      angles[i] += step
      curls[i] += (curl - curls[i]) * follow
      rig.setAngle(angles[i])
    }

    // The shadow map only depends on the pose, never on the camera: redraw it while the fingers
    // move and keep the last one while they rest (which is all of the idle orbit).
    const state = motion.current
    state.stillFor = moved > STILL_EPSILON ? 0 : state.stillFor + dt
    const moving = state.stillFor < STILL_AFTER
    if (moving) gl.shadowMap.needsUpdate = true
    if (moving !== state.moving) {
      state.moving = moving
      onMovingChange(moving)
    }

    const command = message?.command ?? null
    const wasHidden = pose.current.presence < 0.01
    const presenceGoal = ghostEnabled && command ? 1 : 0
    pose.current.presence += (presenceGoal - pose.current.presence) * damp(GHOST_FADE_RATE, dt)
    ghost.setVisible(pose.current.presence > 0.01)
    if (command) {
      for (const rig of ghost.fingers) {
        const i = rig.index
        const target = rig.lower + command[i] * rig.travel
        // A ghost that fades in should already be at the command, not sweep there from zero.
        ghostAngles[i] = wasHidden ? target : ghostAngles[i] + (target - ghostAngles[i]) * follow
        rig.setAngle(ghostAngles[i])
        // Loud while the finger is still travelling to its target, a faint outline once it has arrived.
        const divergence = Math.min(1, Math.abs(command[i] - curls[i]) / GHOST_FULL_AT)
        ghost.setPresence(rig, pose.current.presence * MathUtils.lerp(GHOST_SETTLED, 1, divergence))
      }
    }

    nodes.current ??= resolveHud(hud)
    if (!nodes.current) return
    solid.root.updateMatrixWorld()
    camera.updateMatrixWorld()
    const { tips, order, rows } = callouts.current
    for (const rig of solid.fingers) {
      const point = rig.tip.getWorldPosition(projected.current).project(camera)
      const tip = tips[rig.index]
      tip.x = (point.x * 0.5 + 0.5) * size.width
      tip.y = (-point.y * 0.5 + 0.5) * size.height
      tip.shown = point.z < 1
    }

    // Rows follow the tips' screen order, pushed apart to the pitch and kept inside the column.
    // Two rows trade places only once their tips are a full row apart, so chips never flicker.
    const { chipWidth, inset, elbow, pitch, top, bottom } = LABEL_LAYOUT
    if (Number.isNaN(rows[0])) order.sort((a, b) => tips[a].y - tips[b].y)
    for (let pass = 0; pass < order.length; pass++) {
      for (let i = 0; i + 1 < order.length; i++) {
        const [upper, lower] = [order[i], order[i + 1]]
        if (tips[upper].y <= tips[lower].y + pitch) continue
        // The two chips keep their rows and trade fingers, so they never slide through each other.
        order[i] = lower
        order[i + 1] = upper
        const row = rows[upper]
        rows[upper] = rows[lower]
        rows[lower] = row
      }
    }
    const floor = Math.max(top, size.height - bottom)
    const ease = damp(LABEL_RATE, dt)
    let previous = top - pitch
    order.forEach((finger, rank) => {
      const lowest = floor - (order.length - 1 - rank) * pitch
      const goal = Math.max(previous + pitch, Math.min(tips[finger].y, lowest))
      previous = goal
      rows[finger] = Number.isNaN(rows[finger]) ? goal : rows[finger] + (goal - rows[finger]) * ease
    })

    const column = size.width - inset - chipWidth
    for (const rig of solid.fingers) {
      const item = nodes.current.labels[rig.index]
      const tip = tips[rig.index]
      const row = rows[rig.index]
      const opacity = tip.shown ? "1" : "0"
      item.dot.style.transform = `translate3d(${tip.x.toFixed(1)}px, ${tip.y.toFixed(1)}px, 0)`
      item.dot.style.opacity = opacity
      item.chip.style.transform = `translate3d(0, ${row.toFixed(1)}px, 0)`
      item.chip.style.opacity = opacity
      item.leader.style.opacity = opacity
      item.leader.setAttribute(
        "points",
        `${tip.x.toFixed(1)},${tip.y.toFixed(1)} ${(column - elbow).toFixed(1)},${row.toFixed(1)} ${column},${row.toFixed(1)}`,
      )
      const text = `${Math.round(curls[rig.index] * 100)}%`
      if (text !== item.text) {
        item.text = text
        item.value.textContent = text
      }
    }
  })

  return (
    <>
      <primitive object={solid.root} />
      <primitive object={ghost.root} />
    </>
  )
}

/** Orbit controls, preset transitions, the idle orbit, and the HUD's gizmo and readout. */
function CameraRig({
  model,
  view,
  reducedMotion,
  hud,
  onFreeLook,
}: Pick<HandSceneProps, "view" | "reducedMotion" | "hud" | "onFreeLook"> & { model: HandModel }) {
  const controls = useRef<OrbitControlsImpl>(null)
  const aspect = useThree((state) => state.size.width / Math.max(1, state.size.height))
  const fit = fitDistance(model.bounds.radius, aspect)
  const target = model.bounds.center

  const rig = useRef({
    goal: null as Spherical | null,
    /** Where the camera should look; presets aim past the fingers into the map. */
    lookAt: target.clone(),
    placed: false,
    orbitAfter: 0,
    /** Current idle orbit speed, rad/s. */
    spin: 0,
    current: new Spherical(),
    offset: new Vector3(),
    axis: new Vector3(),
    inverse: new Quaternion(),
    lastQuaternion: new Quaternion(0, 0, 0, 0),
    lastPosition: new Vector3(),
    nodes: null as HudNodes | null,
    readout: "",
  })

  useEffect(() => {
    if (!view) return
    const { azimuth, polar, distance = 1, ahead = 0 } = VIEW_ANGLES[view]
    rig.current.goal = new Spherical(fit * distance, polar, azimuth)
    // The fingers point at +Z, so "ahead" is along it.
    rig.current.lookAt.set(target.x, target.y, target.z + ahead)
  }, [view, fit, target])

  useFrame(({ camera }, rawDt) => {
    const dt = Math.min(rawDt, MAX_FRAME_DT)
    const orbit = controls.current
    if (!orbit) return
    const state = rig.current
    const { current, offset } = state

    if (!state.placed) {
      // Opening move: start wide and off-axis, then settle into the first preset.
      state.placed = true
      const start = state.goal ?? new Spherical(fit, VIEW_ANGLES.iso.polar, VIEW_ANGLES.iso.azimuth)
      const lead = reducedMotion ? 0 : 1
      current.set(start.radius * (1 + 0.35 * lead), start.phi - 0.18 * lead, start.theta - 0.7 * lead)
      camera.position.setFromSpherical(current).add(target)
      orbit.update()
    }

    const goal = state.goal
    if (goal) {
      const k = reducedMotion ? 1 : damp(VIEW_RATE, dt)
      // The look-at point glides with the camera, so a preset pans and dollies as one move.
      const dLook = orbit.target.distanceTo(state.lookAt)
      orbit.target.lerp(state.lookAt, k)
      current.setFromVector3(offset.copy(camera.position).sub(orbit.target))
      const dTheta = MathUtils.euclideanModulo(goal.theta - current.theta + Math.PI, Math.PI * 2) - Math.PI
      const dPhi = goal.phi - current.phi
      const dRadius = goal.radius - current.radius
      current.set(current.radius + dRadius * k, current.phi + dPhi * k, current.theta + dTheta * k)
      camera.position.setFromSpherical(current).add(orbit.target)
      orbit.update()
      if (Math.abs(dTheta) + Math.abs(dPhi) + (Math.abs(dRadius) + dLook) / goal.radius < VIEW_DONE) state.goal = null
    }

    // Idle orbit, advanced by elapsed time. OrbitControls' own autoRotate turns a fixed angle per
    // frame, so every uneven frame shows up as a change of speed (and a fast display spins faster).
    const idle = !goal && !reducedMotion && allowsAutoOrbit(view) && performance.now() > state.orbitAfter
    state.spin += ((idle ? ORBIT_SPEED : 0) - state.spin) * damp(ORBIT_EASE_RATE, dt)
    if (state.spin > ORBIT_SPEED * 1e-3) {
      current.setFromVector3(offset.copy(camera.position).sub(orbit.target))
      current.theta -= state.spin * dt
      camera.position.setFromSpherical(current).add(orbit.target)
      orbit.update()
    } else {
      state.spin = 0
    }

    state.nodes ??= resolveHud(hud)
    if (!state.nodes) return
    if (state.lastQuaternion.equals(camera.quaternion) && state.lastPosition.equals(camera.position)) return
    state.lastQuaternion.copy(camera.quaternion)
    state.lastPosition.copy(camera.position)
    state.inverse.copy(camera.quaternion).invert()

    for (const { axis, group, line, label } of state.nodes.axes) {
      const seen = state.axis.copy(ROS_AXES[axis]).applyQuaternion(state.inverse)
      line.setAttribute("x2", (seen.x * GIZMO_AXIS_PX).toFixed(2))
      line.setAttribute("y2", (-seen.y * GIZMO_AXIS_PX).toFixed(2))
      label.setAttribute("x", (seen.x * GIZMO_LABEL_PX).toFixed(2))
      label.setAttribute("y", (-seen.y * GIZMO_LABEL_PX).toFixed(2))
      group.setAttribute("opacity", (0.3 + 0.7 * (seen.z * 0.5 + 0.5)).toFixed(2))
    }

    current.setFromVector3(offset.copy(camera.position).sub(orbit.target))
    const azimuth = Math.round(MathUtils.euclideanModulo(MathUtils.radToDeg(current.theta), 360)) % 360
    const elevation = 90 - MathUtils.radToDeg(current.phi)
    const pad = (value: number) => String(Math.round(value)).padStart(3, "0")
    const text = `AZ ${pad(azimuth)}°  EL ${pad(elevation)}°  D ${pad(current.radius * 1000)} mm`
    if (text !== state.readout) {
      state.readout = text
      state.nodes.readout.textContent = text
    }
  })

  return (
    <OrbitControls
      ref={controls}
      makeDefault
      target={target}
      enablePan={false}
      enableDamping
      dampingFactor={0.08}
      rotateSpeed={0.7}
      zoomSpeed={0.6}
      minDistance={fit * 0.55}
      maxDistance={fit * MAX_ZOOM_OUT}
      minPolarAngle={VIEW_ANGLES.top.polar}
      maxPolarAngle={Math.PI / 2}
      onStart={() => {
        rig.current.goal = null
        rig.current.spin = 0
        rig.current.orbitAfter = Number.POSITIVE_INFINITY
        onFreeLook()
      }}
      onEnd={() => {
        rig.current.orbitAfter = performance.now() + AUTO_ORBIT_RESUME_MS
      }}
    />
  )
}

function Stage({ description, view, ghost, reducedMotion, hud, onFreeLook }: HandSceneProps) {
  const models = useMemo(
    () => ({ solid: buildHandModel(description, "solid"), ghost: buildHandModel(description, "ghost") }),
    [description],
  )

  const [moving, setMoving] = useState(true)

  useEffect(
    () => () => {
      models.solid.dispose()
      models.ghost.dispose()
    },
    [models],
  )

  return (
    <>
      <Studio model={models.solid} moving={moving} />
      {/* The rig moves the camera first, so the labels project through this frame's view. */}
      <CameraRig model={models.solid} view={view} reducedMotion={reducedMotion} hud={hud} onFreeLook={onFreeLook} />
      <Hand solid={models.solid} ghost={models.ghost} ghostEnabled={ghost} hud={hud} onMovingChange={setMoving} />
      {/* After the hand: its camera_link must be in the scene before objects are portalled into it. */}
      <WorldLayer model={models.solid} hud={hud} />
    </>
  )
}

export default function HandScene(props: HandSceneProps) {
  return (
    <Canvas
      shadows="percentage"
      dpr={[1, 1.5]}
      camera={{ fov: FOV_DEG, near: 0.01, far: 20, position: [0.3, 0.3, 0.3] }}
      gl={{ antialias: true, powerPreference: "high-performance" }}
      onCreated={({ gl, camera }) => {
        gl.toneMapping = NeutralToneMapping
        // The shadow map is redrawn on request (see Hand), not every frame.
        gl.shadowMap.autoUpdate = false
        camera.layers.enable(OVERLAY_LAYER)
      }}
    >
      <Stage {...props} />
    </Canvas>
  )
}
