"use client"

import { useEffect, useRef, useState, type RefObject } from "react"

import { PixelSampler } from "@/components/camera/pixel-sampler"

const BINS = 16
const SAMPLE_WIDTH = 64
const SAMPLE_HEIGHT = 48
const SAMPLE_MS = 500

/**
 * Exposure at a glance: a luma histogram of the current frame, bright at the top
 * (square-root scaled, so thin tails stay visible next to the peak).
 * The RGB panel's counterpart of the depth legend, so both images share one frame.
 */
export function LumaRail({ canvasRef }: { canvasRef: RefObject<HTMLCanvasElement | null> }) {
  const bars = useRef<HTMLOListElement | null>(null)
  const [mean, setMean] = useState<number | null>(null)

  useEffect(() => {
    const sampler = new PixelSampler(SAMPLE_WIDTH, SAMPLE_HEIGHT)
    const counts = new Uint32Array(BINS)

    const sample = () => {
      const canvas = canvasRef.current
      const pixels = canvas && sampler.read(canvas, 0, 0, canvas.width, canvas.height)
      if (!pixels || !bars.current) return
      counts.fill(0)
      let total = 0
      for (let i = 0; i < pixels.length; i += 4) {
        const luma = 0.2126 * pixels[i] + 0.7152 * pixels[i + 1] + 0.0722 * pixels[i + 2]
        counts[Math.min(BINS - 1, Math.floor((luma / 256) * BINS))]++
        total += luma
      }
      const peak = Math.max(...counts)
      Array.from(bars.current.children).forEach((bar, i) => {
        ;(bar as HTMLElement).style.transform = `scaleX(${Math.sqrt(counts[BINS - 1 - i] / peak).toFixed(3)})`
      })
      setMean(total / (pixels.length / 4) / 255)
    }

    sample()
    const timer = setInterval(sample, SAMPLE_MS)
    return () => clearInterval(timer)
  }, [canvasRef])

  return (
    <div className="flex h-full flex-col gap-2">
      <span className="label-micro">Luma</span>
      <ol ref={bars} aria-hidden className="flex min-h-0 flex-1 flex-col gap-px border-l border-ink-mute/50">
        {Array.from({ length: BINS }, (_, i) => (
          <li
            key={i}
            className="min-h-0 flex-1 origin-left bg-ink/70 transition-transform duration-300 ease-out motion-reduce:transition-none"
            style={{ transform: "scaleX(0)" }}
          />
        ))}
      </ol>
      <span className="label-micro flex items-baseline gap-1.5">
        Mean
        <span className="num text-[10px] tracking-normal text-ink-soft">{mean === null ? "--" : mean.toFixed(2)}</span>
      </span>
    </div>
  )
}
