"use client"

import { useEffect, useRef } from "react"
import { animate, motion, useMotionValue, useReducedMotion, useTransform } from "motion/react"

import { cn } from "@/lib/utils"

const EASE = [0.22, 1, 0.36, 1] as const
const COUNT_UP_S = 0.9

interface TweenedNumberProps {
  /** null renders the placeholder (no data). */
  value: number | null
  digits?: number
  /** Always show the sign: "+3", "-12", "+0". */
  signed?: boolean
  /** Tween length between live updates; the first value counts up more slowly. */
  duration?: number
  /** Seconds to hold the first count-up, to line it up with the panel entrance. */
  delay?: number
  placeholder?: string
  className?: string
}

/** A mono, tabular number that tweens between values without re-rendering React. */
export function TweenedNumber({
  value,
  digits = 0,
  signed = false,
  duration = 0.25,
  delay = 0,
  placeholder = "--",
  className,
}: TweenedNumberProps) {
  const reduced = useReducedMotion()
  const current = useMotionValue(0)
  const text = useTransform(current, (v) => {
    // Sim noise sits a hair below zero; never print it as "-0".
    const fixed = v.toFixed(digits).replace(/^-(?=[0.]*$)/, "")
    if (!signed) return fixed
    return Number(fixed) < 0 ? fixed : `+${fixed}`
  })
  /** `performance.now()` at which the count-up starts; null while there is no data. */
  const startAt = useRef<number | null>(null)

  useEffect(() => {
    if (value === null) {
      startAt.current = null
      current.set(0)
      return
    }
    if (reduced) {
      current.set(value)
      return
    }
    // Live values keep arriving during the count-up, so each retarget only gets what is left of it.
    const now = performance.now()
    startAt.current ??= now + delay * 1000
    const wait = Math.max(0, startAt.current - now) / 1000
    const remaining = (startAt.current - now) / 1000 + COUNT_UP_S - wait
    const controls =
      remaining > duration
        ? animate(current, value, { duration: remaining, delay: wait, ease: EASE })
        : animate(current, value, { duration, ease: "linear" })
    return () => controls.stop()
  }, [value, reduced, current, duration, delay])

  if (value === null) return <span className={cn("num", className)}>{placeholder}</span>
  return <motion.span className={cn("num", className)}>{text}</motion.span>
}
