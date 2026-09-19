"use client"

import { AnimatePresence, motion } from "motion/react"

const BRACKETS = [
  "top-2 left-2 border-t border-l",
  "top-2 right-2 border-t border-r",
  "bottom-2 left-2 border-b border-l",
  "right-2 bottom-2 border-r border-b",
] as const

const FADE = { initial: { opacity: 0 }, animate: { opacity: 1 }, exit: { opacity: 0 }, transition: { duration: 0.3 } }

/** Strokes are doubled (soft ink under white) so they hold on any image. */
function Reticle() {
  const marks = (
    <>
      <circle cx="32" cy="32" r="9" />
      <path d="M32 4v16M32 44v16M4 32h16M44 32h16" />
      <path d="M32 27v2M32 35v2M27 32h2M35 32h2" />
    </>
  )
  return (
    <motion.svg
      aria-hidden
      viewBox="0 0 64 64"
      fill="none"
      className="absolute top-1/2 left-1/2 size-16 -translate-x-1/2 -translate-y-1/2"
      {...FADE}
    >
      <g stroke="var(--ink)" strokeOpacity="0.35" strokeWidth="2.5">
        {marks}
      </g>
      <g stroke="#fff" strokeWidth="1">
        {marks}
      </g>
      <circle cx="32" cy="32" r="1.25" fill="#fff" />
    </motion.svg>
  )
}

function ThirdsGrid() {
  return (
    <motion.svg aria-hidden className="absolute inset-0 size-full" {...FADE}>
      {["33.333%", "66.667%"].map((at) => (
        <g key={at} stroke="#fff" strokeOpacity="0.7" strokeWidth="1" strokeDasharray="2 4">
          <line x1={at} x2={at} y1="0" y2="100%" />
          <line y1={at} y2={at} x1="0" x2="100%" />
        </g>
      ))}
    </motion.svg>
  )
}

export interface CameraHudProps {
  held: boolean
  grid: boolean
  /** A cursor probe is on the image: its crosshair replaces the centre reticle. */
  probing: boolean
}

/**
 * Viewfinder overlay drawn over the letterboxed image. Never takes pointer events, and
 * carries no accent: the panel header's status dot is the one live mark per camera.
 */
export function CameraHud({ held, grid, probing }: CameraHudProps) {
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      <AnimatePresence>{grid && <ThirdsGrid key="grid" />}</AnimatePresence>

      {BRACKETS.map((corner) => (
        <span key={corner} aria-hidden className={`absolute size-3 border-white drop-shadow-[0_0_1px_var(--ink)] ${corner}`} />
      ))}
      <AnimatePresence>{!probing && <Reticle key="reticle" />}</AnimatePresence>

      <AnimatePresence>
        {held && (
          <motion.span
            key="hold"
            className="label-micro absolute top-2 left-1/2 flex -translate-x-1/2 items-center gap-1.5 border border-hairline bg-surface px-1.5 py-0.5 text-ink"
            {...FADE}
            transition={{ duration: 0.18 }}
          >
            <span aria-hidden className="size-1.5 bg-ink" />
            Hold
          </motion.span>
        )}
      </AnimatePresence>
    </div>
  )
}
