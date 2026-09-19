"use client"

import { useEffect, useRef } from "react"

import { HISTORY_CAPACITY, HISTORY_SECONDS, useSimStore } from "@/lib/sim-store"
import { FINGERS } from "@/lib/types"
import { cn } from "@/lib/utils"

const PAD_Y = 4
const PAD_RIGHT = 5
const GRID_LEVELS = [0, 0.5, 1] as const

interface SparklineProps {
  /** Index into finger order. */
  finger: number
  /** Data is not flowing: the trace freezes and fades. */
  dimmed: boolean
  className?: string
}

/**
 * Last ~10 s of one finger's measured curl, with the commanded level as a
 * dashed rule. Drawn from the store's ring buffer on requestAnimationFrame;
 * React never sees the samples.
 */
export function Sparkline({ finger, dimmed, className }: SparklineProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    const context = canvas?.getContext("2d")
    if (!canvas || !context) return

    const tokens = getComputedStyle(canvas)
    const ink = tokens.getPropertyValue("--ink").trim()
    const inkMute = tokens.getPropertyValue("--ink-mute").trim()
    const surface = tokens.getPropertyValue("--surface").trim()

    const values = new Float32Array(HISTORY_CAPACITY)
    const times = new Float64Array(HISTORY_CAPACITY)
    let width = 0
    let height = 0
    let drawnKey = ""
    let frame = 0
    const alpha = dimmed ? 0.4 : 1

    const observer = new ResizeObserver(([entry]) => {
      const ratio = window.devicePixelRatio || 1
      width = entry.contentRect.width
      height = entry.contentRect.height
      canvas.width = Math.round(width * ratio)
      canvas.height = Math.round(height * ratio)
      context.setTransform(ratio, 0, 0, ratio, 0, 0)
      drawnKey = ""
    })
    observer.observe(canvas)

    const draw = () => {
      frame = requestAnimationFrame(draw)
      if (width === 0 || height === 0) return

      const { history, message } = useSimStore.getState().live
      const count = history.read(finger, values)
      history.readTimes(times)
      const newest = count > 0 ? times[count - 1] : 0
      const command = message?.command?.[finger] ?? null
      const key = `${newest}|${command}`
      if (key === drawnKey) return
      drawnKey = key

      const plotWidth = width - PAD_RIGHT
      const x = (t: number) => plotWidth * (1 - (newest - t) / HISTORY_SECONDS)
      const y = (v: number) => height - PAD_Y - v * (height - PAD_Y * 2)

      context.clearRect(0, 0, width, height)

      context.lineWidth = 1
      context.strokeStyle = ink
      context.setLineDash([])
      for (const level of GRID_LEVELS) {
        const gridY = Math.round(y(level)) + 0.5
        context.globalAlpha = alpha * (level === 0 ? 0.16 : 0.07)
        context.beginPath()
        context.moveTo(0, gridY)
        context.lineTo(width, gridY)
        context.stroke()
      }
      context.globalAlpha = alpha
      if (count < 2) return

      const first = Math.max(0, x(times[0]))
      context.beginPath()
      context.moveTo(first, y(values[0]))
      for (let i = 1; i < count; i++) context.lineTo(Math.max(0, x(times[i])), y(values[i]))

      context.lineJoin = "round"
      context.lineWidth = 1.25
      context.strokeStyle = dimmed ? inkMute : ink
      context.stroke()

      context.lineTo(plotWidth, y(0))
      context.lineTo(first, y(0))
      context.closePath()
      context.fillStyle = ink
      context.globalAlpha = alpha * 0.05
      context.fill()
      context.globalAlpha = alpha

      if (command !== null) {
        const commandY = Math.round(y(command)) + 0.5
        context.setLineDash([2, 3])
        context.lineWidth = 1
        context.strokeStyle = inkMute
        context.beginPath()
        context.moveTo(0, commandY)
        context.lineTo(width, commandY)
        context.stroke()
        context.setLineDash([])
      }

      const headY = y(values[count - 1])
      context.beginPath()
      context.arc(plotWidth, headY, 3.5, 0, Math.PI * 2)
      context.fillStyle = surface
      context.fill()
      context.beginPath()
      context.arc(plotWidth, headY, 2, 0, Math.PI * 2)
      context.fillStyle = dimmed ? inkMute : ink
      context.fill()
    }
    frame = requestAnimationFrame(draw)

    return () => {
      cancelAnimationFrame(frame)
      observer.disconnect()
    }
  }, [finger, dimmed])

  return (
    <div className={cn("relative min-h-0 min-w-0", className)}>
      <canvas
        ref={canvasRef}
        role="img"
        aria-label={`${FINGERS[finger]} curl, last ${HISTORY_SECONDS} seconds`}
        className="absolute inset-0 size-full"
      />
    </div>
  )
}
