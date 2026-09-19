"use client"

import { motion } from "motion/react"

import { PanelNotice, type PanelNoticeProps } from "@/components/console/panel"

/** Empty state for a camera with nothing to show: the shared notice over a crossed-out frame. */
export function SignalNotice(props: PanelNoticeProps) {
  return (
    <motion.div
      className="absolute inset-0"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.4 }}
    >
      <svg aria-hidden className="absolute inset-0 size-full text-hairline" stroke="currentColor">
        <line x1="0" y1="0" x2="100%" y2="100%" />
        <line x1="100%" y1="0" x2="0" y2="100%" />
      </svg>
      <PanelNotice {...props} />
    </motion.div>
  )
}
