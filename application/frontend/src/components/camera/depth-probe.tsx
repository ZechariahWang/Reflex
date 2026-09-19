"use client"

import { useEffect, useRef, useState, type PointerEvent, type RefObject } from "react"
import { AnimatePresence, motion } from "motion/react"

import { PixelSampler } from "@/components/camera/pixel-sampler"
import { nearnessOf } from "@/lib/depth-ramp"

interface ProbePoint {
  /** CSS pixels inside the image. */
  x: number
  y: number
  /** Source pixel. */
  px: number
  py: number
  flipX: boolean
  flipY: boolean
}

const CHIP_WIDTH_PX = 124
const CHIP_HEIGHT_PX = 44
const OFFSET_PX = 12
/** Averaged neighbourhood, which takes the edge off JPEG noise. */
const SAMPLE_PX = 3
/** The scene moves under a resting cursor, so the reading refreshes on its own. */
const REFRESH_MS = 200

export interface DepthProbeProps {
  /** Source image size. */
  width: number
  height: number
  minMm: number
  maxMm: number
  /** The canvas currently on screen (live or held). */
  canvasRef: RefObject<HTMLCanvasElement | null>
  onProbingChange: (probing: boolean) => void
}

/**
 * Cursor probe for the depth view. The stream is a colorized JPEG, so depth is read back
 * by inverting the colormap under the cursor: approximate, and clamped to the range.
 */
export function DepthProbe({ width, height, minMm, maxMm, canvasRef, onProbingChange }: DepthProbeProps) {
  const [point, setPoint] = useState<ProbePoint | null>(null)
  const [reading, setReading] = useState("")
  const sampler = useRef<PixelSampler | null>(null)

  useEffect(() => {
    if (!point) return
    const read = () => {
      const canvas = canvasRef.current
      sampler.current ??= new PixelSampler(1, 1)
      const left = Math.min(Math.max(point.px - 1, 0), width - SAMPLE_PX)
      const top = Math.min(Math.max(point.py - 1, 0), height - SAMPLE_PX)
      const pixel = canvas && sampler.current.read(canvas, left, top, SAMPLE_PX, SAMPLE_PX)
      if (!pixel) return setReading("--")
      const nearness = nearnessOf([pixel[0], pixel[1], pixel[2]])
      if (nearness === null) return setReading("VOID")
      const metres = ((maxMm - (maxMm - minMm) * nearness) / 1000).toFixed(2)
      setReading(`${nearness < 0.005 ? "≥" : nearness > 0.995 ? "≤" : "≈"} ${metres} m`)
    }
    read()
    const timer = setInterval(read, REFRESH_MS)
    return () => clearInterval(timer)
  }, [point, canvasRef, width, height, minMm, maxMm])

  const track = (event: PointerEvent<HTMLDivElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect()
    const x = Math.min(Math.max(event.clientX - bounds.left, 0), bounds.width)
    const y = Math.min(Math.max(event.clientY - bounds.top, 0), bounds.height)
    if (!point) onProbingChange(true)
    setPoint({
      x,
      y,
      px: Math.min(Math.floor((x / bounds.width) * width), width - 1),
      py: Math.min(Math.floor((y / bounds.height) * height), height - 1),
      flipX: x + OFFSET_PX + CHIP_WIDTH_PX > bounds.width,
      flipY: y + OFFSET_PX + CHIP_HEIGHT_PX > bounds.height,
    })
  }

  const leave = () => {
    setPoint(null)
    onProbingChange(false)
  }

  return (
    <div className="absolute inset-0 cursor-crosshair touch-none" onPointerMove={track} onPointerLeave={leave}>
      <AnimatePresence>
        {point && (
          <motion.div
            className="pointer-events-none absolute inset-0"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
          >
            <span className="absolute inset-y-0 w-px bg-ink/40" style={{ left: point.x }} />
            <span className="absolute inset-x-0 h-px bg-ink/40" style={{ top: point.y }} />
            <span
              className="absolute size-1.5 -translate-x-1/2 -translate-y-1/2 border border-ink bg-surface"
              style={{ left: point.x, top: point.y }}
            />
            <div
              className="num absolute grid grid-cols-[auto_1fr] gap-x-2 border border-hairline bg-surface px-2 py-1.5 text-[10px] leading-[14px] text-ink"
              style={{
                width: CHIP_WIDTH_PX,
                left: point.flipX ? point.x - OFFSET_PX - CHIP_WIDTH_PX : point.x + OFFSET_PX,
                top: point.flipY ? point.y - OFFSET_PX - CHIP_HEIGHT_PX : point.y + OFFSET_PX,
              }}
            >
              <span className="text-ink-mute">Z</span>
              <span className="text-right text-[11px]">{reading}</span>
              <span className="text-ink-mute">PX</span>
              <span className="text-right text-ink-soft">
                {point.px} {point.py}
              </span>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
