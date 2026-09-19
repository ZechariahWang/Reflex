"use client"

import { useCallback, useEffect, useRef, useState } from "react"

import { StatusDot } from "@/components/console/status-dot"
import { CommandThrottle } from "@/components/telemetry/command-throttle"
import { Button } from "@/components/ui/button"
import { Slider } from "@/components/ui/slider"
import { Switch } from "@/components/ui/switch"
import { selectIsLive, selectSnapshot, useSimStore } from "@/lib/sim-store"
import { FINGERS, TOPIC_NAMES, type FingerValues } from "@/lib/types"
import { cn } from "@/lib/utils"

/** Commands leave at most this often (~20 Hz), always as the full five-vector. */
const SEND_INTERVAL_MS = 50
/** After the last input the sliders keep the local target this long, until /hand/command echoes back. */
const HOLD_MS = 600
const POSE_TOLERANCE = 0.02
/** Slider thumb height (h-1.5): Radix insets the thumb's travel by it, and the measured tick follows. */
const THUMB_PX = 6
const OPEN_HAND: FingerValues = [0, 0, 0, 0, 0]

const PRESETS: readonly { name: string; pose: FingerValues }[] = [
  { name: "Open", pose: OPEN_HAND },
  { name: "Fist", pose: [1, 1, 1, 1, 1] },
  { name: "Pinch", pose: [1, 1, 0, 0, 0] },
  { name: "Point", pose: [1, 0, 1, 1, 1] },
  { name: "Peace", pose: [1, 0, 0, 1, 1] },
]

const matches = (a: FingerValues, b: FingerValues) => a.every((v, i) => Math.abs(v - b[i]) <= POSE_TOLERANCE)

/**
 * Publishes to /hand/command. Read-only until armed; disarms itself whenever
 * the socket or ROS drops, so a reconnect can never resume sending on its own.
 */
export function CommandBlock() {
  const online = useSimStore(selectIsLive)
  const snapshot = useSimStore(selectSnapshot)
  const [armed, setArmed] = useState(false)
  /** Local target while the user is driving; null = mirror the hand. */
  const [target, setTarget] = useState<FingerValues | null>(null)

  const [throttle] = useState(
    () => new CommandThrottle((data) => useSimStore.getState().sendCommand(data), SEND_INTERVAL_MS),
  )
  const holdTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clearTimers = useCallback(() => {
    throttle.cancel()
    if (holdTimer.current !== null) clearTimeout(holdTimer.current)
    holdTimer.current = null
  }, [throttle])

  const disarm = useCallback(() => {
    clearTimers()
    setArmed(false)
    setTarget(null)
  }, [clearTimers])

  useEffect(() => {
    const unsubscribe = useSimStore.subscribe((store) => {
      if (!selectIsLive(store)) disarm()
    })
    return () => {
      unsubscribe()
      clearTimers()
    }
  }, [disarm, clearTimers])

  const drive = (next: FingerValues) => {
    if (holdTimer.current !== null) clearTimeout(holdTimer.current)
    holdTimer.current = null
    setTarget(next)
    throttle.push(next)
  }

  const release = () => {
    if (holdTimer.current !== null) clearTimeout(holdTimer.current)
    holdTimer.current = setTimeout(() => {
      holdTimer.current = null
      setTarget(null)
    }, HOLD_MS)
  }

  const measured = online ? (snapshot?.state ?? null) : null
  // Sliders start from where the hand already is, so grabbing one never makes it jump.
  const shown = target ?? (online ? (snapshot?.command ?? snapshot?.state) : null) ?? OPEN_HAND

  return (
    <div className="flex h-full min-w-0 gap-5 px-3 py-2.5">
      <div className="flex flex-col gap-2">
        <span className="label-micro flex items-center justify-between gap-3 text-ink">
          Command
          <span className="flex items-center gap-1 text-ink-mute" aria-hidden>
            <span className="h-px w-2 bg-ink" />
            Meas
          </span>
        </span>
        <div className="flex h-20 min-h-0 gap-2.5 console:h-auto console:flex-1">
          {FINGERS.map((finger, i) => (
            <div key={finger} className="flex flex-col items-center gap-1.5">
              <div className="relative flex min-h-0 w-4 flex-1 justify-center">
                <Slider
                  orientation="vertical"
                  min={0}
                  max={100}
                  step={1}
                  disabled={!armed}
                  value={[Math.round(shown[i] * 100)]}
                  onValueChange={([value]) => drive(shown.with(i, value / 100) as FingerValues)}
                  onValueCommit={release}
                  aria-label={`${finger} command`}
                  className="data-vertical:min-h-0! [&_[data-slot=slider-thumb]]:h-1.5 [&_[data-slot=slider-thumb]]:w-3.5 [&_[data-slot=slider-thumb]]:rounded-[1px] [&_[data-slot=slider-thumb]]:border-ink [&_[data-slot=slider-range]]:rounded-none [&_[data-slot=slider-track]]:rounded-none [&_[data-slot=slider-track]]:bg-ink/10"
                />
                {measured && (
                  <span
                    aria-hidden
                    className="pointer-events-none absolute -right-1.5 h-px w-2 bg-ink"
                    style={{ bottom: `calc(${measured[i].toFixed(2)} * (100% - ${THUMB_PX}px) + ${THUMB_PX / 2 - 0.5}px)` }}
                  />
                )}
              </div>
              <span className="label-micro">{finger[0]}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="flex min-w-0 flex-1 flex-col gap-3">
        <label className="flex items-center justify-between gap-3">
          <span className="flex min-w-0 items-center gap-2">
            <StatusDot status={armed ? "live" : "offline"} />
            <span className={cn("label-micro", armed && "text-ink")}>{armed ? "Armed" : "Safe"}</span>
            <span className="label-micro truncate leading-4 tracking-normal normal-case">
              {armed ? "publishing" : online ? "read-only" : "no link"}
            </span>
          </span>
          <Switch
            size="sm"
            checked={armed}
            disabled={!online}
            onCheckedChange={(next) => (next ? setArmed(true) : disarm())}
            aria-label="Arm command publishing"
            className="rounded-[2px] data-checked:bg-signal [&_[data-slot=switch-thumb]]:rounded-[1px]"
          />
        </label>

        <div className="grid grid-cols-5 gap-1">
          {PRESETS.map(({ name, pose }) => (
            <Button
              key={name}
              variant="outline"
              size="xs"
              disabled={!armed}
              onClick={() => {
                drive(pose)
                release()
              }}
              className={cn(
                "label-micro h-6 rounded-[2px] bg-surface px-0 tracking-[0.06em] disabled:border-hairline disabled:text-ink-mute disabled:opacity-100",
                armed && matches(shown, pose) ? "border-ink text-ink" : "text-ink-soft",
              )}
            >
              {name}
            </Button>
          ))}
        </div>

        <p className="label-micro mt-auto leading-[1.5] tracking-normal normal-case">
          {armed
            ? `publishing ${TOPIC_NAMES.hand_command} · 20 Hz max`
            : online
              ? `arm to publish ${TOPIC_NAMES.hand_command}`
              : "arming needs a live hand"}
        </p>
      </div>
    </div>
  )
}
