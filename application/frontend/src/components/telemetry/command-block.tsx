"use client"

import { useCallback, useEffect, useRef, useState } from "react"

import { StatusDot } from "@/components/console/status-dot"
import { CommandThrottle } from "@/components/telemetry/command-throttle"
import { Button } from "@/components/ui/button"
import { Slider } from "@/components/ui/slider"
import { Switch } from "@/components/ui/switch"
import { setMirrorEnabled, useMirrorStore } from "@/lib/mirror-store"
import { selectIsLive, selectPassive, selectPolicy, selectSnapshot, useSimStore } from "@/lib/sim-store"
import { FINGERS, TOPIC_NAMES, type FingerValues } from "@/lib/types"
import { cn } from "@/lib/utils"

/** Commands leave at most this often (~40 Hz), always as the full five-vector. */
const SEND_INTERVAL_MS = 25 // a slider drag reaches the HAL (50 Hz) on its very next tick
/** After the last input the sliders keep the local target this long, until /hand/command echoes back. */
const HOLD_MS = 600
const POSE_TOLERANCE = 0.02
/** Slider thumb width (w-1.5): Radix insets the thumb's travel by it, and the measured tick follows. */
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
  // Backdrive: the HAL has the torque off and ignores commands while a person moves the fingers.
  const passive = useSimStore(selectPassive)
  // Mirror teleop: the controller's webcam is the command source, so the sliders and presets lock.
  const mirror = useMirrorStore((store) => store.enabled)
  // The learned policy (policy/run_policy.sh): while it runs it owns /hand/command, so the rest locks.
  const policy = useSimStore(selectPolicy)
  const policyOn = policy === "running"
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
    setMirrorEnabled(false)
    if (selectPolicy(useSimStore.getState()) === "running") useSimStore.getState().setPolicy(false)
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

  const switchClass = "rounded-[2px] data-checked:bg-signal [&_[data-slot=switch-thumb]]:rounded-[1px]"

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 px-3 py-2">
      <label className="flex items-center gap-2">
        <StatusDot status={armed ? "live" : "offline"} />
        <span className={cn("label-micro", armed && "text-ink")}>{armed ? "Armed" : "Safe"}</span>
        <Switch
          size="sm"
          checked={armed}
          disabled={!online}
          onCheckedChange={(next) => (next ? setArmed(true) : disarm())}
          aria-label="Arm command publishing"
          className={switchClass}
        />
      </label>
      <label className="flex items-center gap-2">
        <StatusDot status={passive ? "live" : "offline"} />
        <span className={cn("label-micro", passive && "text-ink")}>Backdrive</span>
        <Switch
          size="sm"
          checked={passive}
          disabled={!armed || mirror || policyOn}
          onCheckedChange={(next) => useSimStore.getState().setPassive(next)}
          aria-label="Backdrive mode: torque off, move the fingers by hand"
          className={switchClass}
        />
      </label>
      <label className="flex items-center gap-2">
        <StatusDot status={mirror ? "live" : "offline"} />
        <span className={cn("label-micro", mirror && "text-ink")}>Mirror</span>
        <Switch
          size="sm"
          checked={mirror}
          disabled={!armed || passive || policyOn}
          onCheckedChange={setMirrorEnabled}
          aria-label="Mirror teleop: a hand in front of the webcam commands the fingers"
          className={switchClass}
        />
      </label>
      <label
        className="flex items-center gap-2"
        title={policy === "offline" ? "No policy runs: start policy/run_policy.sh on the GPU laptop" : undefined}
      >
        <StatusDot status={policyOn ? "live" : "offline"} />
        <span className={cn("label-micro", policyOn && "text-ink")}>Policy</span>
        <Switch
          size="sm"
          checked={policyOn}
          disabled={!armed || passive || mirror || policy === "offline"}
          onCheckedChange={(next) => useSimStore.getState().setPolicy(next)}
          aria-label="Policy: the learned policy moves the fingers; off opens the hand"
          className={switchClass}
        />
      </label>

      <span className="h-4 w-px bg-border" aria-hidden />

      <div className="flex gap-1">
        {PRESETS.map(({ name, pose }) => (
          <Button
            key={name}
            variant="outline"
            size="xs"
            disabled={!armed || passive || mirror || policyOn}
            onClick={() => {
              drive(pose)
              release()
            }}
            className={cn(
              "label-micro h-6 rounded-[2px] bg-surface px-2 tracking-[0.06em] disabled:border-hairline disabled:text-ink-mute disabled:opacity-100",
              armed && matches(shown, pose) ? "border-ink text-ink" : "text-ink-soft",
            )}
          >
            {name}
          </Button>
        ))}
      </div>

      <span className="h-4 w-px bg-border" aria-hidden />

      {/* One slider per finger; the tick under it is the measured position. */}
      <div className="flex items-center gap-3">
        {FINGERS.map((finger, i) => (
          <div key={finger} className="flex items-center gap-1.5">
            <span
              className={snapshot?.blocked?.[i] ? "label-micro text-signal" : "label-micro"}
              title={snapshot?.blocked?.[i] ? "contact stop: holding with low torque" : undefined}
            >
              {finger[0]}
            </span>
            <div className="relative flex h-4 w-20 items-center">
              <Slider
                min={0}
                max={100}
                step={1}
                disabled={!armed || passive || mirror || policyOn}
                value={[Math.round(shown[i] * 100)]}
                onValueChange={([value]) => drive(shown.with(i, value / 100) as FingerValues)}
                onValueCommit={release}
                aria-label={`${finger} command`}
                className="[&_[data-slot=slider-thumb]]:h-3.5 [&_[data-slot=slider-thumb]]:w-1.5 [&_[data-slot=slider-thumb]]:rounded-[1px] [&_[data-slot=slider-thumb]]:border-ink [&_[data-slot=slider-range]]:rounded-none [&_[data-slot=slider-track]]:rounded-none [&_[data-slot=slider-track]]:bg-ink/10"
              />
              {measured && (
                <span
                  aria-hidden
                  className="pointer-events-none absolute -bottom-1 h-2 w-px bg-ink"
                  style={{ left: `calc(${measured[i].toFixed(2)} * (100% - ${THUMB_PX}px) + ${THUMB_PX / 2 - 0.5}px)` }}
                />
              )}
            </div>
            {snapshot?.current && (
              <span
                className={`label-micro w-6 text-right tabular-nums tracking-normal ${snapshot.blocked?.[i] ? "text-signal" : ""}`}
                title="motor current, mA: the peak of the last half second"
              >
                {Math.round(snapshot.current[i])}
              </span>
            )}
          </div>
        ))}
      </div>

      <span className="label-micro min-w-0 truncate tracking-normal normal-case">
        {passive
          ? `torque off: move the fingers by hand, ${TOPIC_NAMES.hand_state} records them`
          : mirror
            ? `the webcam hand publishes ${TOPIC_NAMES.hand_command}`
            : policyOn
              ? `the policy publishes ${TOPIC_NAMES.hand_command} · off opens the hand`
            : armed
              ? `publishing ${TOPIC_NAMES.hand_command} · 40 Hz max`
              : online
                ? `arm to publish ${TOPIC_NAMES.hand_command}`
                : "arming needs a live hand"}
      </span>
    </div>
  )
}
