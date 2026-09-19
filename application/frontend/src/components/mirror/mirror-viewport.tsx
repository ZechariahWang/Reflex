"use client"

import { useCallback, useEffect, useRef } from "react"

import { Panel, PanelNotice } from "@/components/console/panel"
import type { Status } from "@/components/console/status-dot"
import { Button } from "@/components/ui/button"
import { useMirror, type MirrorLink } from "@/hooks/use-mirror"
import { useSimStore } from "@/lib/sim-store"
import { FINGERS, type FingerValues, type MirrorMode, type MirrorPose, type MirrorStatus } from "@/lib/types"
import { cn } from "@/lib/utils"

/** MediaPipe's hand skeleton: pairs of landmark indices. */
const BONES: readonly [number, number][] = [
  [0, 1], [1, 2], [2, 3], [3, 4],
  [0, 5], [5, 6], [6, 7], [7, 8],
  [5, 9], [9, 10], [10, 11], [11, 12],
  [9, 13], [13, 14], [14, 15], [15, 16],
  [13, 17], [17, 18], [18, 19], [19, 20],
  [0, 17],
] // prettier-ignore
const INK = "#242424"
const PAPER = "#ffffff"

const BARS = ["ctl", "cmd", "st"] as const
const BAR_TITLES: Record<(typeof BARS)[number], string> = {
  ctl: "controller: your hand",
  cmd: "command: sent to the hand",
  st: "state: measured on the hand",
}

const MODES: Record<MirrorMode, { status: Status; label: string; hint: string }> = {
  off: { status: "offline", label: "Off", hint: "calibrate to start" },
  no_hand: { status: "waiting", label: "No hand", hint: "put your hand in view" },
  frozen: { status: "waiting", label: "Frozen", hint: "match the cmd bars" },
  following: { status: "live", label: "Following", hint: "the hand copies you" },
}

const LINK_NOTICES: Record<Exclude<MirrorLink, "open">, { status: Status; label: string; hint: string }> = {
  camera: { status: "waiting", label: "Webcam", hint: "allow the camera for this page" },
  "no-camera": { status: "offline", label: "No webcam", hint: "needs a camera and localhost or https" },
  connecting: { status: "waiting", label: "Connecting", hint: "opening /ws/mirror" },
  busy: { status: "offline", label: "In use", hint: "another controller is connected, retrying" },
}

const POSE_PROMPT: Record<MirrorPose, string> = {
  open: "Open your hand flat, fingers apart",
  fist: "Make a fist, thumb closed too",
}

const CAPTURE_ERRORS: Record<string, string> = {
  no_hand: "no hand was seen: start again",
  range: "a finger moved too little between open and fist: start again",
}

/** Panel 01 while Mirror is on: the controller's webcam, what the backend sees in it, and what it sends. */
export function MirrorViewport() {
  const overlayRef = useRef<HTMLCanvasElement | null>(null)
  const barRefs = useRef<(HTMLSpanElement | null)[]>([])

  const onFrame = useCallback((status: MirrorStatus) => {
    const state = useSimStore.getState().live.message?.state ?? null
    const rows: (FingerValues | null)[] = [status.controller, status.command, state]
    rows.forEach((values, row) =>
      FINGERS.forEach((_, finger) => {
        const bar = barRefs.current[finger * BARS.length + row]
        if (bar) bar.style.height = `${((values?.[finger] ?? 0) * 100).toFixed(1)}%`
      }),
    )

    const canvas = overlayRef.current
    const context = canvas?.getContext("2d")
    if (!canvas || !context) return
    const { width, height } = canvas
    context.clearRect(0, 0, width, height)
    if (!status.landmarks) return
    const points = status.landmarks.map(([x, y]) => [x * width, y * height] as const)
    context.lineWidth = 2
    context.strokeStyle = PAPER
    context.beginPath()
    for (const [a, b] of BONES) {
      context.moveTo(...points[a])
      context.lineTo(...points[b])
    }
    context.stroke()
    context.fillStyle = INK
    for (const [x, y] of points) {
      context.beginPath()
      context.arc(x, y, 3.5, 0, 2 * Math.PI)
      context.fill()
      context.stroke()
    }
  }, [])

  const { videoRef, link, summary, calibrate } = useMirror(onFrame)
  const { mode, calibrated, capturing, error, step } = summary
  const capture = useCallback(() => {
    if (step && !capturing) calibrate(step)
  }, [step, capturing, calibrate])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.code !== "Space" || event.repeat) return
      event.preventDefault() // Space would also press whichever button has the focus
      capture()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [capture])

  const shown = link === "open" ? MODES[mode] : LINK_NOTICES[link]
  const guiding = link === "open" && (step !== null || capturing !== null)

  return (
    <Panel
      index="01"
      title="Mirror"
      tag="/ws/mirror"
      status={shown.status}
      statusLabel={shown.label}
      actions={
        link === "open" && calibrated ? (
          <Button
            variant="outline"
            size="xs"
            onClick={() => calibrate("open")}
            className="label-micro h-6 rounded-[2px] bg-surface"
          >
            Recalibrate
          </Button>
        ) : undefined
      }
      footer={
        <>
          <span>{shown.hint}</span>
          <span>webcam: tracking only, never recorded</span>
        </>
      }
      contentClassName="grid grid-rows-[minmax(0,1fr)_auto] console:grid-cols-[minmax(0,1fr)_19rem] console:grid-rows-1"
    >
      <div className="relative min-h-0 bg-ink/5">
        {/* A selfie view: the frames go to the backend unflipped, the bends do not depend on it. */}
        <div
          className={cn(
            "absolute inset-3 -scale-x-100 border-2",
            mode === "following" ? "border-transparent" : "border-destructive",
          )}
        >
          <video ref={videoRef} autoPlay muted playsInline className="size-full object-contain" />
          {/* Same 4:3 box as the video, so 0..1 landmarks land on the image. */}
          <canvas ref={overlayRef} width={640} height={480} className="absolute inset-0 size-full object-contain" />
        </div>

        {link !== "open" && <PanelNotice {...shown} />}

        {guiding && (
          <div className="absolute inset-x-0 bottom-6 flex justify-center px-4">
            <div className="flex flex-col items-center gap-2 border border-hairline bg-surface px-5 py-3 text-center">
              <span className="label-micro text-ink">
                {capturing ? `Capturing ${capturing}: hold still` : step && POSE_PROMPT[step]}
              </span>
              {error && !capturing && (
                <span className="label-micro tracking-normal normal-case text-destructive">
                  {CAPTURE_ERRORS[error] ?? error}
                </span>
              )}
              <Button size="xs" disabled={capturing !== null} onClick={capture} className="label-micro h-6 rounded-[2px]">
                Capture {step ?? capturing} · Space
              </Button>
            </div>
          </div>
        )}
      </div>

      <div className="flex min-h-0 gap-3 border-t px-3 py-2.5 console:border-t-0 console:border-l">
        {FINGERS.map((finger, i) => (
          <div key={finger} className="flex min-w-0 flex-1 flex-col items-center gap-1.5">
            <div className="flex h-24 min-h-0 w-full gap-px console:h-auto console:flex-1">
              {BARS.map((bar, row) => (
                <span key={bar} title={BAR_TITLES[bar]} className="relative flex-1 bg-ink/10">
                  <span
                    ref={(element) => {
                      barRefs.current[i * BARS.length + row] = element
                    }}
                    className={cn("absolute inset-x-0 bottom-0", bar === "cmd" ? "bg-signal" : "bg-ink", bar === "st" && "opacity-50")}
                    style={{ height: 0 }}
                  />
                </span>
              ))}
            </div>
            <span className="label-micro flex w-full justify-between tracking-normal normal-case" aria-hidden>
              {BARS.map((bar) => (
                <span key={bar} className="flex-1 text-center text-[8px]">
                  {bar}
                </span>
              ))}
            </span>
            <span className="label-micro">{finger}</span>
          </div>
        ))}
      </div>
    </Panel>
  )
}
