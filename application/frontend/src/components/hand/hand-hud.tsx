"use client"

import { createRef, useState, type RefObject } from "react"

import { Toggle } from "@/components/ui/toggle"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { FINGERS, TOPIC_NAMES, type Finger } from "@/lib/types"
import { cn } from "@/lib/utils"

import { VIEW_PRESETS, type ViewPreset } from "./views"

/**
 * DOM nodes the three.js scene writes to every frame (positions, numbers),
 * so nothing in the HUD re-renders through React at frame rate.
 */
export interface HudRefs {
  labels: RefObject<HTMLDivElement | null>
  gizmo: RefObject<SVGSVGElement | null>
  readout: RefObject<HTMLSpanElement | null>
}

/** One stable set of refs for the lifetime of the viewport. */
export function useHudRefs(): HudRefs {
  const [refs] = useState<HudRefs>(() => ({
    labels: createRef<HTMLDivElement>(),
    gizmo: createRef<SVGSVGElement>(),
    readout: createRef<HTMLSpanElement>(),
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
