"use client"

import { Sparkline } from "@/components/telemetry/sparkline"
import { TweenedNumber } from "@/components/console/tweened-number"
import { FINGERS } from "@/lib/types"
import { cn } from "@/lib/utils"

/** live = ROS data flowing; stale = API up, ROS down (last known values); offline = no API. */
export type Flow = "live" | "stale" | "offline"

/** Seconds the first count-up waits, so it starts as the panel finishes its entrance. */
const COUNT_UP_DELAY_S = 0.5
/** Command and state closer than this (in %) read as "on target". */
const DELTA_VISIBLE_PCT = 1

interface FingerColumnProps {
  /** Index into finger order. */
  finger: number
  flow: Flow
  /** Measured curl 0..1. */
  state: number | null
  /** Commanded curl 0..1; null until someone publishes one. */
  command: number | null
  radians: number | null
}

export function FingerColumn({ finger, flow, state, command, radians }: FingerColumnProps) {
  const offline = flow === "offline"
  const curl = offline || state === null ? null : state * 100
  const target = offline || command === null ? null : command * 100
  const delta = curl !== null && target !== null ? target - curl : null
  const ink = flow === "live" ? "text-ink" : "text-ink-mute"

  return (
    <div className="flex min-w-0 flex-col gap-2 px-3 py-2.5">
      <div className="flex items-baseline justify-between gap-2">
        <span className="label-micro flex gap-2">
          <span className="num">{String(finger + 1).padStart(2, "0")}</span>
          <span className={ink}>{FINGERS[finger]}</span>
        </span>
        <span className="label-micro tracking-normal whitespace-nowrap normal-case">
          <TweenedNumber value={offline ? null : radians} digits={2} duration={0.1} delay={COUNT_UP_DELAY_S} /> rad
        </span>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-2 console:flex-row console:gap-3">
        <div className="flex w-16 shrink-0 flex-col justify-end gap-1.5">
          <span className="flex items-baseline gap-1">
            <TweenedNumber
              value={curl}
              duration={0.1}
              delay={COUNT_UP_DELAY_S}
              className={cn("text-[22px] leading-none tracking-tight 2xl:text-[28px]", ink)}
            />
            <span className="label-micro">%</span>
          </span>
          <span className="label-micro tracking-normal normal-case">
            cmd <TweenedNumber value={target} duration={0.1} delay={COUNT_UP_DELAY_S} className="text-ink-soft" />
          </span>
        </div>
        <Sparkline finger={finger} dimmed={flow !== "live"} className="h-10 shrink-0 console:h-auto console:flex-1" />
      </div>

      {/* No CSS transitions here: a transition restarted at the 10 Hz snapshot rate falls behind on a slow renderer. */}
      <div className="relative">
        <div className="relative h-2.5" aria-hidden>
          <div className="absolute inset-x-0 top-1/2 h-[3px] -translate-y-1/2 bg-ink/8" />
          <div
            className={cn(
              "absolute inset-x-0 top-1/2 h-[3px] origin-left -translate-y-1/2",
              flow === "live" ? "bg-ink" : "bg-ink-mute",
            )}
            style={{ transform: `scaleX(${(curl ?? 0) / 100})` }}
          />
          {target !== null && (
            <div
              className="absolute inset-y-0 w-px bg-ink"
              style={{ left: `${target}%` }}
            />
          )}
        </div>
        <span
          className={cn(
            "label-micro absolute right-0 bottom-full mb-1 bg-surface pl-1 tracking-normal transition-opacity duration-300",
            delta !== null && Math.abs(delta) >= DELTA_VISIBLE_PCT ? "opacity-100" : "opacity-0",
          )}
        >
          {"\u0394"}
          <TweenedNumber value={delta} signed duration={0.1} placeholder="" />
        </span>
      </div>
    </div>
  )
}
