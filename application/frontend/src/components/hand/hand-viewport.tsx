"use client"

import { useCallback, useState, useSyncExternalStore } from "react"
import dynamic from "next/dynamic"
import { AnimatePresence, motion, useReducedMotion } from "motion/react"

import { Panel, PanelNotice } from "@/components/console/panel"
import type { Status } from "@/components/console/status-dot"
import { useHealth } from "@/hooks/use-health"
import { selectIsLive, selectObjects, selectStatus, useSimStore, type SimStore } from "@/lib/sim-store"
import { TOPIC_NAMES } from "@/lib/types"
import { cn } from "@/lib/utils"

import { AxisGizmo, CameraReadout, GhostToggle, ObjectLabels, Radar, TipLabels, ViewPresets, useHudRefs } from "./hand-hud"
import { SceneBoundary } from "./scene-boundary"
import { useUrdf } from "./use-urdf"
import type { ViewPreset } from "./views"

// three.js touches WebGL and the DOM on import, so the scene never renders on the server.
const HandScene = dynamic(() => import("./hand-scene"), { ssr: false })

const URDF_TOPIC = "/robot_description"
/** How the model is stood up in the viewport; the gizmo shows the same frame. */
const FRAME_NOTE = "base_link, +Z up"
const EASE = [0.22, 1, 0.36, 1] as const
/** Gaps shorter than this (first message, a quick reconnect) never raise the notice. */
const NOTICE_DELAY_S = 1.2
const FADE = { duration: 0.6, ease: EASE } as const

const selectHasData = (store: SimStore): boolean => store.snapshot !== null
const selectHasCommand = (store: SimStore): boolean => store.snapshot?.command != null

let webglSupport: boolean | null = null

function detectWebgl(): boolean {
  if (webglSupport === null) {
    try {
      webglSupport = document.createElement("canvas").getContext("webgl2") !== null
    } catch {
      webglSupport = false
    }
  }
  return webglSupport
}

const subscribeNever = () => () => {}

function useWebglSupport(): boolean {
  return useSyncExternalStore(subscribeNever, detectWebgl, () => true)
}

export function HandViewport() {
  const urdf = useUrdf()
  const webgl = useWebglSupport()
  const socket = useSimStore(selectStatus)
  const live = useSimStore(selectIsLive)
  const hasData = useSimStore(selectHasData)
  const hasCommand = useSimStore(selectHasCommand)
  const { reachable } = useHealth()
  const reducedMotion = useReducedMotion() ?? false
  const hud = useHudRefs()
  const [failed, setFailed] = useState(false)
  const sceneFailed = useCallback(() => setFailed(true), [])

  const objects = useSimStore(selectObjects)

  const [view, setView] = useState<ViewPreset | null>("iso")
  const [ghost, setGhost] = useState(true)
  const freeLook = useCallback(() => setView(null), [])
  // The first objects to appear pull the camera back into the map view, once; after that the
  // presets are the user's. (State derived during render, as React recommends over an effect.)
  const [mapShown, setMapShown] = useState(false)
  if (!mapShown && objects.length > 0) {
    setMapShown(true)
    if (view === "iso") setView("chase")
  }

  const ready = webgl && !failed && urdf !== null
  const linked = socket === "open"
  // A link that was up and dropped, or an API that never answered; until then it is still connecting.
  const unreachable = !linked && (hasData || reachable === false)

  // Same wording as the telemetry panel: Live / No ROS / Offline / Connecting.
  let status: Status = "waiting"
  let statusLabel = "Connecting"
  if (!webgl || failed) {
    status = "offline"
    statusLabel = webgl ? "Failed" : "No WebGL"
  } else if (live) {
    statusLabel = urdf ? "Live" : "Loading"
    if (urdf) status = "live"
  } else if (linked) {
    statusLabel = "No ROS"
  } else if (unreachable) {
    status = "offline"
    statusLabel = "Offline"
  }

  return (
    <Panel
      index="01"
      title="Hand"
      tag={TOPIC_NAMES.joint_states}
      status={status}
      statusLabel={statusLabel}
      contentClassName="bg-page"
      footer={
        <>
          <span className="truncate leading-4 tracking-normal normal-case">
            {urdf ? `${urdf.name} · ${urdf.linkCount} links · ${urdf.jointCount} joints · ${FRAME_NOTE}` : URDF_TOPIC}
          </span>
          <span className="flex shrink-0 items-center gap-4">
            {ready && <CameraReadout readoutRef={hud.readout} />}
            <span>Grid 10 mm · Rings 25 cm</span>
          </span>
        </>
      }
    >
      {ready && (
        <>
          <motion.div
            className={cn("absolute inset-0 transition-[filter] duration-700", !live && "grayscale")}
            initial={{ opacity: 0 }}
            animate={{ opacity: live ? 1 : 0.55 }}
            transition={{ duration: 0.9, ease: EASE }}
          >
            <SceneBoundary onError={sceneFailed}>
              <HandScene
                description={urdf}
                view={view}
                ghost={ghost}
                reducedMotion={reducedMotion}
                hud={hud}
                onFreeLook={freeLook}
              />
            </SceneBoundary>
          </motion.div>

          <motion.div
            className={cn("pointer-events-none absolute inset-0 transition-[filter] duration-700", !live && "grayscale")}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ ...FADE, delay: 0.5 }}
          >
            <ObjectLabels objectsRef={hud.objects} objects={objects} stale={!live} />
            <TipLabels labelsRef={hud.labels} stale={!live} />
            <div className="pointer-events-auto absolute top-3 left-3">
              <ViewPresets view={view} onChange={setView} />
            </div>
            <div className="pointer-events-auto absolute top-3 right-3">
              <GhostToggle enabled={ghost} hasCommand={hasCommand} onChange={setGhost} />
            </div>
            <div className="absolute bottom-2 left-3 flex items-end gap-4">
              <AxisGizmo gizmoRef={hud.gizmo} />
              <Radar radarRef={hud.radar} objects={objects} />
            </div>
          </motion.div>
        </>
      )}

      <AnimatePresence>
        {!webgl && (
          <motion.div key="no-webgl" className="absolute inset-0" exit={{ opacity: 0 }} transition={FADE}>
            <PanelNotice status="offline" label="WebGL unavailable" hint="enable hardware acceleration to view the hand" />
          </motion.div>
        )}
        {failed && (
          <motion.div key="failed" className="absolute inset-0" exit={{ opacity: 0 }} transition={FADE}>
            <PanelNotice status="offline" label="3D view failed" hint="reload to retry" />
          </motion.div>
        )}
        {webgl && !failed && !urdf && (
          <motion.div key={unreachable ? "no-model" : "loading"} className="absolute inset-0" exit={{ opacity: 0 }} transition={FADE}>
            {unreachable ? (
              <PanelNotice status="offline" label="No model" detail={URDF_TOPIC} hint="backend unreachable, retrying" />
            ) : (
              <PanelNotice status="waiting" label="Awaiting model" detail={URDF_TOPIC} hint="waiting for the robot description" />
            )}
          </motion.div>
        )}
        {ready && !live && (
          <motion.div
            key="held"
            className="pointer-events-none absolute inset-x-0 bottom-4 flex justify-center"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0, transition: { ...FADE, delay: NOTICE_DELAY_S } }}
            exit={{ opacity: 0, y: 6 }}
            transition={FADE}
          >
            <span className="label-micro border border-hairline bg-surface px-2.5 py-1.5 text-ink-soft">
              {linked ? "ROS disconnected" : "Backend unreachable"} · holding last pose
            </span>
          </motion.div>
        )}
      </AnimatePresence>
    </Panel>
  )
}
