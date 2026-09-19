"use client"

import { createRef, useState, type RefObject } from "react"

import { Toggle } from "@/components/ui/toggle"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { FINGERS, TOPIC_NAMES, type Finger, type TrackedObject } from "@/lib/types"
import { cn } from "@/lib/utils"

import { VIEW_PRESETS, type ViewPreset } from "./views"
import { RADAR_RADIUS, RADAR_RANGE_M, RANGE_RINGS_M, shortLabel } from "./world-layer"

/**
 * DOM nodes the three.js scene writes to every frame (positions, numbers),
 * so nothing in the HUD re-renders through React at frame rate.
 */
export interface HudRefs {
  labels: RefObject<HTMLDivElement | null>
  gizmo: RefObject<SVGSVGElement | null>
  readout: RefObject<HTMLSpanElement | null>
  /** Object callouts; the world layer positions every `[data-object]`. */
  objects: RefObject<HTMLDivElement | null>
  /** Top-down radar; the world layer moves every `[data-object]` group. */
  radar: RefObject<SVGSVGElement | null>
}

/** One stable set of refs for the lifetime of the viewport. */
export function useHudRefs(): HudRefs {
  const [refs] = useState<HudRefs>(() => ({
    labels: createRef<HTMLDivElement>(),
    gizmo: createRef<SVGSVGElement>(),
    readout: createRef<HTMLSpanElement>(),
    objects: createRef<HTMLDivElement>(),
    radar: createRef<SVGSVGElement>(),
  }))
  return refs
}

export type GizmoAxis = "x" | "y" | "z"

/** The resolved nodes, looked up once so the frame loop never queries the DOM. */
export interface HudNodes {
  /** Finger order. `text` is what `value` currently shows. */
  labels: { dot: HTMLElement; leader: SVGPolylineElement; chip: HTMLElement; value: HTMLElement; text: string }[]
  axes: { axis: GizmoAxis; group: SVGGElement; line: SVGLineElement; label: SVGTextElement }[]
  readout: HTMLElement
}

/** Null until every HUD element is mounted. */
export function resolveHud(refs: HudRefs): HudNodes | null {
  const labels = refs.labels.current
  const gizmo = refs.gizmo.current
  const readout = refs.readout.current
  if (!labels || !gizmo || !readout) return null
  return {
    labels: FINGERS.map((finger) => {
      const part = <T extends Element>(role: string) => labels.querySelector<T>(`[data-finger="${finger}"][data-part="${role}"]`)!
      const chip = part<HTMLElement>("chip")
      return {
        dot: part<HTMLElement>("dot"),
        leader: part<SVGPolylineElement>("leader"),
        chip,
        value: chip.querySelector<HTMLElement>("[data-value]")!,
        text: "",
      }
    }),
    axes: GIZMO_AXES.map((axis) => {
      const group = gizmo.querySelector<SVGGElement>(`[data-axis="${axis}"]`)!
      return { axis, group, line: group.querySelector("line")!, label: group.querySelector("text")! }
    }),
    readout,
  }
}

const GIZMO_AXES: readonly GizmoAxis[] = ["x", "y", "z"]

const SHORT_NAME: Record<Finger, string> = {
  thumb: "THM",
  index: "IDX",
  middle: "MID",
  ring: "RNG",
  pinky: "PNK",
}

/** Callout column geometry, shared with the scene that lays the labels out every frame. */
export const LABEL_LAYOUT = {
  chipWidth: 76,
  chipHeight: 20,
  /** Panel edge to the chips' right side. */
  inset: 12,
  /** Horizontal run of the leader into the chip. */
  elbow: 18,
  /** Minimum distance between chip centres. */
  pitch: 28,
  /** Column limits, clear of the ghost toggle above and the pose notice below. */
  top: 72,
  bottom: 56,
} as const

const CONTROL =
  "h-6 min-w-0 rounded-none! px-2 font-mono text-[10px] tracking-[0.14em] text-ink-mute uppercase hover:bg-page hover:text-ink"

/**
 * Fingertip callouts: a dot on each tip, an elbow leader, and the value in a fixed column on
 * the right edge, so the tags never sit on the model or on each other. The scene positions
 * every `[data-part]` and fills `[data-value]`. `stale` = the pose is held, not live.
 */
export function TipLabels({ labelsRef, stale }: { labelsRef: HudRefs["labels"]; stale: boolean }) {
  return (
    <div
      ref={labelsRef}
      aria-hidden
      className={cn(
        "pointer-events-none absolute inset-0 overflow-hidden transition-opacity duration-700",
        stale && "opacity-40",
      )}
    >
      <svg className="absolute inset-0 size-full" fill="none">
        {FINGERS.map((finger) => (
          <polyline key={finger} data-finger={finger} data-part="leader" className="stroke-ink/25" strokeWidth="1" />
        ))}
      </svg>
      {FINGERS.map((finger) => (
        <span
          key={finger}
          data-finger={finger}
          data-part="dot"
          className="absolute -top-[2.5px] -left-[2.5px] size-[5px] rounded-full border border-ink bg-surface opacity-0 will-change-transform"
        />
      ))}
      {FINGERS.map((finger) => (
        <div
          key={finger}
          data-finger={finger}
          data-part="chip"
          className="absolute top-0 flex items-center justify-between border border-hairline bg-surface px-1.5 opacity-0 will-change-transform"
          style={{
            right: LABEL_LAYOUT.inset,
            width: LABEL_LAYOUT.chipWidth,
            height: LABEL_LAYOUT.chipHeight,
            marginTop: -LABEL_LAYOUT.chipHeight / 2,
          }}
        >
          <span className="label-micro">{SHORT_NAME[finger]}</span>
          <span data-value className={cn("num text-[11px] leading-none", stale ? "text-ink-mute" : "text-ink")}>
            0%
          </span>
        </div>
      ))}
    </div>
  )
}

export function ViewPresets({
  view,
  onChange,
}: {
  view: ViewPreset | null
  onChange: (view: ViewPreset) => void
}) {
  return (
    <ToggleGroup
      type="single"
      size="sm"
      spacing={0}
      value={view ?? ""}
      onValueChange={(next) => {
        if (next) onChange(next as ViewPreset)
      }}
      aria-label="Camera view"
      className="rounded-none! border border-hairline bg-surface"
    >
      {VIEW_PRESETS.map((preset) => (
        <ToggleGroupItem
          key={preset}
          value={preset}
          className={cn(
            CONTROL,
            "border-l border-hairline first:border-l-0 data-[state=on]:bg-ink data-[state=on]:text-surface",
          )}
        >
          {preset}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  )
}

/** Ghost switch plus the legend that explains the two hands. */
export function GhostToggle({
  enabled,
  hasCommand,
  onChange,
}: {
  enabled: boolean
  hasCommand: boolean
  onChange: (enabled: boolean) => void
}) {
  return (
    <div className="flex flex-col items-end gap-1.5">
      <Toggle
        size="sm"
        pressed={enabled}
        onPressedChange={onChange}
        aria-label="Show the commanded pose as a ghost"
        className={cn(
          CONTROL,
          "gap-1.5 border border-hairline bg-surface aria-pressed:bg-surface aria-pressed:text-ink",
          enabled && (hasCommand ? "border-signal/50 aria-pressed:bg-signal-soft" : "border-ink/40"),
        )}
      >
        <span
          className={cn(
            "size-1.5 border",
            !enabled && "border-ink-mute",
            enabled && (hasCommand ? "border-signal bg-signal" : "border-ink"),
          )}
        />
        Ghost
      </Toggle>
      {enabled && (
        <span className="label-micro tracking-normal normal-case">
          {hasCommand ? `wireframe = ${TOPIC_NAMES.hand_command}` : `awaiting ${TOPIC_NAMES.hand_command}`}
        </span>
      )}
    </div>
  )
}

/** ROS axes (Z-up) as seen by the camera; the scene rotates each `[data-axis]`. */
export function AxisGizmo({ gizmoRef }: { gizmoRef: HudRefs["gizmo"] }) {
  return (
    <svg
      ref={gizmoRef}
      aria-hidden
      viewBox="-32 -32 64 64"
      className="size-16 overflow-visible font-mono text-[9px] text-ink-soft"
    >
      <circle r="1.5" className="fill-ink" />
      {GIZMO_AXES.map((axis) => (
        <g key={axis} data-axis={axis}>
          <line x1="0" y1="0" x2="0" y2="0" stroke="currentColor" strokeWidth="1" />
          <text textAnchor="middle" dominantBaseline="central" fill="currentColor">
            {axis.toUpperCase()}
          </text>
        </g>
      ))}
    </svg>
  )
}

/** Camera azimuth / elevation / distance, written by the scene. */
export function CameraReadout({ readoutRef }: { readoutRef: HudRefs["readout"] }) {
  return <span ref={readoutRef} className="label-micro num" />
}

/**
 * Callouts for the objects around the hand: a dot on each one and a chip with its label,
 * distance and how long ago it was seen. The world layer moves them and fills the numbers;
 * an object in view has the accent, a remembered one is drawn in ink and fades with age.
 */
export function ObjectLabels({ objectsRef, objects, stale }: { objectsRef: HudRefs["objects"]; objects: TrackedObject[]; stale: boolean }) {
  return (
    <div
      ref={objectsRef}
      aria-hidden
      className={cn(
        "pointer-events-none absolute inset-0 overflow-hidden transition-opacity duration-700",
        stale && "opacity-40",
      )}
    >
      {objects.map((object) => (
        <span
          key={object.id}
          data-object={object.id}
          data-part="dot"
          className="absolute -top-[3px] -left-[3px] size-1.5 rounded-full border border-ink bg-surface opacity-0 will-change-transform data-[seen=1]:border-signal data-[seen=1]:bg-signal"
        />
      ))}
      {objects.map((object) => (
        <div
          key={object.id}
          data-object={object.id}
          data-part="chip"
          className="group absolute top-0 left-0 flex w-[8.5rem] flex-col gap-1 border border-hairline bg-surface px-1.5 py-1 whitespace-nowrap opacity-0 will-change-transform data-[seen=1]:border-ink/40"
        >
          <span className="flex items-baseline justify-between gap-2">
            <span className="label-micro truncate text-ink">{shortLabel(object)}</span>
            <span data-distance className="num text-[11px] leading-none text-ink" />
          </span>
          <span className="flex items-center justify-between gap-2">
            <span data-age className="label-micro tracking-normal normal-case group-data-[seen=1]:text-signal" />
            <span className="label-micro num tracking-normal">{Math.round(object.confidence * 100)}%</span>
          </span>
          <span className="relative h-px w-full bg-hairline">
            <span data-bar className="absolute inset-0 origin-left bg-ink transition-none group-data-[seen=1]:bg-signal" />
          </span>
        </div>
      ))}
    </div>
  )
}

/**
 * Top-down map: the hand at the centre pointing up, the same range rings as the ground, and a
 * dot per object that the world layer moves (the accent while in view). Objects beyond the outer
 * ring sit on its edge.
 */
export function Radar({ radarRef, objects }: { radarRef: HudRefs["radar"]; objects: TrackedObject[] }) {
  const scale = RADAR_RADIUS / RADAR_RANGE_M
  return (
    <div className="flex flex-col items-start gap-1">
      <svg
        ref={radarRef}
        aria-label="Objects around the hand, top-down"
        viewBox="-50 -50 100 100"
        className="size-[6.5rem] overflow-visible font-mono text-[7px] text-ink-soft"
      >
        <circle r={RADAR_RADIUS} className="fill-surface/70 stroke-hairline" strokeWidth="1" />
        {RANGE_RINGS_M.map((radius) => (
          <g key={radius}>
            <circle r={radius * scale} fill="none" className="stroke-ink/15" strokeWidth="0.75" />
            <text x={radius * scale + 1.5} y="-1.5" fill="currentColor" className="text-[6px]">
              {radius < 1 ? `${Math.round(radius * 100)}` : "1m"}
            </text>
          </g>
        ))}
        <line x1="0" y1={-RADAR_RADIUS} x2="0" y2={RADAR_RADIUS} className="stroke-ink/10" strokeWidth="0.75" />
        <line x1={-RADAR_RADIUS} y1="0" x2={RADAR_RADIUS} y2="0" className="stroke-ink/10" strokeWidth="0.75" />
        {/* The hand: a small wedge, fingers up. */}
        <path d="M0,-4.5 L3,3 L0,1.2 L-3,3 Z" className="fill-ink" />
        {objects.map((object) => (
          // Dots only: the chips in the scene carry the names, and clustered labels would pile up here.
          <g key={object.id} data-object={object.id} opacity="0" className="[&[data-seen='1']_circle]:fill-signal [&[data-seen='1']_circle]:stroke-signal">
            <circle r="2" className="fill-surface stroke-ink" strokeWidth="1" />
          </g>
        ))}
      </svg>
      <span className="label-micro pl-1">
        {objects.length === 0 ? "no objects" : `${objects.length} object${objects.length === 1 ? "" : "s"}`}
      </span>
    </div>
  )
}
