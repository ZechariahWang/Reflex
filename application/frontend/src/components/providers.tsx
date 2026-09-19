"use client"

import type { ReactNode } from "react"
import { MotionConfig } from "motion/react"

import { TooltipProvider } from "@/components/ui/tooltip"
import { useSimConnection } from "@/lib/sim-store"

/** App-wide client context: owns the /ws/state connection, tooltips, reduced-motion policy. */
export function Providers({ children }: { children: ReactNode }) {
  useSimConnection()

  return (
    <MotionConfig reducedMotion="user">
      <TooltipProvider delayDuration={150}>{children}</TooltipProvider>
    </MotionConfig>
  )
}
