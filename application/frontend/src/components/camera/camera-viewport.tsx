"use client"

import { useRef, useState, type ReactNode } from "react"
import { Grid3x3, ImageDown, Maximize2, Minimize2, Pause, Play } from "lucide-react"
import { AnimatePresence, motion } from "motion/react"

import { CameraHud } from "@/components/camera/camera-hud"
import { DepthLegend } from "@/components/camera/depth-legend"
import { DepthProbe } from "@/components/camera/depth-probe"
import { LumaRail } from "@/components/camera/luma-rail"
import { SignalNotice } from "@/components/camera/signal-notice"
import { useExpandable } from "@/components/camera/use-expandable"
import { useFitRect } from "@/components/camera/use-fit-rect"
import { Panel, type PanelNoticeProps } from "@/components/console/panel"
import type { Status } from "@/components/console/status-dot"
import { Button } from "@/components/ui/button"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useCameraStream, type CameraStreamStatus } from "@/hooks/use-camera-stream"
import { selectRosConnected, useSimStore } from "@/lib/sim-store"
import { TOPIC_NAMES, type CameraKind, type CameraSource } from "@/lib/types"
import { cn } from "@/lib/utils"

/** One panel per camera. The RealSense shows either of its two images; the iPhone has colour only. */
const PANELS: Record<CameraSource, { index: string; title: string; tags: Partial<Record<CameraKind, string>>; lost: string }> = {
  realsense: {
    index: "02",
    title: "RealSense",
    tags: { color: "/camera/color", depth: "/camera/aligned_depth" },
    lost: "camera:=none or unplugged",
  },
  iphone: {
    index: "03",
    title: "iPhone",
    tags: { color: "/head_camera/color" },
    lost: "no frames: start `head_camera:=iphone`, see the node log",
  },
}

const KINDS: readonly { kind: CameraKind; label: string }[] = [
  { kind: "color", label: "RGB" },
  { kind: "depth", label: "Depth" },
]

/** "No signal" is the camera's own fault; a missing backend reads "Offline" here as on every panel. */
const NOTICES: Record<Exclude<CameraStreamStatus, "live">, Required<Pick<PanelNoticeProps, "status" | "label" | "hint">>> = {
  connecting: { status: "waiting", label: "Connecting", hint: "opening stream" },
  "no-signal": { status: "offline", label: "No signal", hint: "camera:=none or unplugged" },
  offline: { status: "offline", label: "Offline", hint: "backend unreachable, retrying" },
}

const PLACEHOLDER = "--"
/** Both rails, on both cameras: the two pixel-aligned images then share one box. */
const RAIL = "hidden w-[4.75rem] shrink-0 p-2.5 @min-[24rem]:block"

const DEFAULT_ASPECT = 4 / 3

function gcd(a: number, b: number): number {
  return b === 0 ? a : gcd(b, a % b)
}

function HeaderAction({
  label,
  pressed,
  disabled,
  onClick,
  children,
}: {
  label: string
  pressed?: boolean
  disabled?: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="ghost"
          size="icon-xs"
          aria-label={label}
          aria-pressed={pressed}
          disabled={disabled}
          onClick={onClick}
          className={cn("rounded-[2px] text-ink-mute hover:text-ink", pressed && "bg-muted text-ink")}
        >
          {children}
        </Button>
      </TooltipTrigger>
      <TooltipContent sideOffset={6} className="label-micro rounded-[2px] text-background">
        {label}
      </TooltipContent>
    </Tooltip>
  )
}

function Readout({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="label-micro">{label}</dt>
      <dd className="num text-[11px] leading-none text-ink">
        {value}
        {unit && <span className="ml-1 text-[9px] text-ink-mute uppercase">{unit}</span>}
      </dd>
    </div>
  )
}

function KindToggle({ kind, onChange }: { kind: CameraKind; onChange: (kind: CameraKind) => void }) {
  return (
    <ToggleGroup
      type="single"
      size="sm"
      spacing={0}
      value={kind}
      onValueChange={(next) => {
        if (next) onChange(next as CameraKind)
      }}
      aria-label="Image"
      className="mr-1.5 rounded-none! border border-hairline bg-surface"
    >
      {KINDS.map((item) => (
        <ToggleGroupItem
          key={item.kind}
          value={item.kind}
          className="h-5 min-w-0 rounded-none! border-l border-hairline px-1.5 font-mono text-[9px] tracking-[0.14em] text-ink-mute uppercase first:border-l-0 hover:bg-page hover:text-ink data-[state=on]:bg-ink data-[state=on]:text-surface"
        >
          {item.label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  )
}

export function CameraViewport({ source }: { source: CameraSource }) {
  const { index, title, tags, lost } = PANELS[source]
  const [kind, setKind] = useState<CameraKind>("color")
  const { canvasRef, frameRef, meta, status, fps } = useCameraStream(source, kind)
  const heldFrameRef = useRef<Blob | null>(null)
  const holdRef = useRef<HTMLCanvasElement | null>(null)
  const [held, setHeld] = useState(false)
  const [grid, setGrid] = useState(false)
  const [probing, setProbing] = useState(false)
  const { slotRef, box, floating, expanded, toggle, collapse } = useExpandable()

  const sized = meta !== null && meta.width > 0 && meta.height > 0
  const { areaRef, rect } = useFitRect<HTMLDivElement>(sized ? meta.width / meta.height : DEFAULT_ASPECT)

  const streaming = status === "live" && meta?.available !== false
  const showImage = streaming || held
  const rosConnected = useSimStore(selectRosConnected)
  const base = NOTICES[status === "live" ? "no-signal" : status]
  const lostHint = rosConnected ? lost : "ros disconnected"
  const notice = base === NOTICES["no-signal"] ? { ...base, hint: lostHint } : base
  const panelStatus: Status = held ? "offline" : streaming ? "live" : notice.status
  const statusLabel = held ? "Hold" : streaming ? "Live" : notice.label

  const switchKind = (next: CameraKind) => {
    setHeld(false)
    setProbing(false)
    setKind(next)
  }

  const toggleHold = () => {
    const live = canvasRef.current
    const hold = holdRef.current
    if (!held && live && hold) {
      hold.width = live.width
      hold.height = live.height
      hold.getContext("2d")?.drawImage(live, 0, 0)
      heldFrameRef.current = frameRef.current // the histogram holds with the picture
    }
    setHeld(!held)
  }

  const saveSnapshot = () => {
    const source = held ? holdRef.current : canvasRef.current
    source?.toBlob((blob) => {
      if (!blob) return
      const link = document.createElement("a")
      link.href = URL.createObjectURL(blob)
      link.download = `${source}-${kind}-${new Date().toISOString().replace(/[:.]/g, "-")}.png`
      link.click()
      URL.revokeObjectURL(link.href)
    }, "image/png")
  }

  const ratio = sized ? gcd(meta.width, meta.height) : 0
  const shownRef = held ? holdRef : canvasRef
  const range = kind === "depth" && meta?.min_mm !== undefined && meta.max_mm !== undefined ? { minMm: meta.min_mm, maxMm: meta.max_mm } : null

  return (
    <div ref={slotRef} className="relative size-full">
      <AnimatePresence>
        {expanded && (
          <motion.div
            aria-hidden
            className="fixed inset-0 z-40 bg-page/80"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.35 }}
            onClick={collapse}
          />
        )}
      </AnimatePresence>

      <motion.div style={box} className={floating ? "fixed z-50" : "relative"}>
        <Panel
          index={index}
          title={title}
          tag={tags[kind]}
          status={panelStatus}
          statusLabel={statusLabel}
          contentClassName="@container flex bg-page/50"
          actions={
            <div className="flex items-center gap-0.5">
              {tags.depth !== undefined && <KindToggle kind={kind} onChange={switchKind} />}
              {kind === "color" && (
                <HeaderAction label="Thirds grid" pressed={grid} onClick={() => setGrid(!grid)}>
                  <Grid3x3 />
                </HeaderAction>
              )}
              <HeaderAction label={held ? "Resume" : "Freeze frame"} pressed={held} disabled={!showImage} onClick={toggleHold}>
                {held ? <Play /> : <Pause />}
              </HeaderAction>
              <HeaderAction label="Save PNG" disabled={!showImage} onClick={saveSnapshot}>
                <ImageDown />
              </HeaderAction>
              <HeaderAction label={expanded ? "Collapse · Esc" : "Expand"} pressed={expanded} onClick={toggle}>
                {expanded ? <Minimize2 /> : <Maximize2 />}
              </HeaderAction>
            </div>
          }
        >
          <div className={cn(RAIL, "border-r")}>
            <dl className="flex h-full flex-col justify-between">
              <Readout label="Res" value={sized ? `${meta.width}×${meta.height}` : PLACEHOLDER} />
              <Readout label="Aspect" value={sized ? `${meta.width / ratio}:${meta.height / ratio}` : PLACEHOLDER} />
              <Readout label="Rate" value={streaming ? String(fps) : PLACEHOLDER} unit="fps" />
              <Readout label="Period" value={streaming && fps > 0 ? String(Math.round(1000 / fps)) : PLACEHOLDER} unit="ms" />
              <Readout label="Source" value={streaming && meta ? String(Math.round(meta.hz)) : PLACEHOLDER} unit="hz" />
            </dl>
          </div>

          <div ref={areaRef} className="relative min-w-0 flex-1">
            <motion.div
              className="absolute overflow-hidden bg-page"
              style={rect ?? { inset: 0 }}
              initial={false}
              animate={{ opacity: showImage ? 1 : 0 }}
              transition={{ duration: 0.4 }}
            >
              <canvas ref={canvasRef} className="absolute inset-0 size-full" />
              <canvas ref={holdRef} className={cn("absolute inset-0 size-full", !held && "invisible")} />
              {showImage && rect && (
                <>
                  <CameraHud held={held} grid={grid} probing={probing} />
                  {range && sized && (
                    <DepthProbe
                      width={meta.width}
                      height={meta.height}
                      {...range}
                      canvasRef={shownRef}
                      onProbingChange={setProbing}
                    />
                  )}
                </>
              )}
            </motion.div>

            <AnimatePresence>
              {!showImage && (
                <SignalNotice
                  key={notice.label + notice.hint}
                  detail={source === "realsense" ? TOPIC_NAMES[kind] : TOPIC_NAMES.iphone}
                  {...notice}
                />
              )}
            </AnimatePresence>
          </div>

          <div className={cn(RAIL, "border-l")}>
            {range && <DepthLegend {...range} />}
            {kind === "color" && showImage && <LumaRail frameRef={held ? heldFrameRef : frameRef} />}
          </div>
        </Panel>
      </motion.div>
    </div>
  )
}
