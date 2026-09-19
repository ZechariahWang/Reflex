import { useEffect, useRef, useState, type RefObject } from "react"

export interface FitRect {
  left: number
  top: number
  width: number
  height: number
}

/**
 * Letterboxes a box of the given aspect ratio inside the observed element
 * (object-contain). Edges are snapped to device pixels so the scaled canvas
 * and the hairlines drawn over it stay crisp on HiDPI screens.
 */
export function useFitRect<T extends HTMLElement>(aspect: number): { areaRef: RefObject<T | null>; rect: FitRect | null } {
  const areaRef = useRef<T | null>(null)
  const [area, setArea] = useState<{ width: number; height: number } | null>(null)

  useEffect(() => {
    const element = areaRef.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      setArea({ width, height })
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  if (!area || area.width <= 0 || area.height <= 0) return { areaRef, rect: null }

  const dpr = typeof window === "undefined" ? 1 : window.devicePixelRatio || 1
  const snap = (value: number) => Math.round(value * dpr) / dpr
  const width = Math.min(area.width, area.height * aspect)
  const height = width / aspect
  const left = snap((area.width - width) / 2)
  const top = snap((area.height - height) / 2)

  return {
    areaRef,
    rect: { left, top, width: snap(left + width) - left, height: snap(top + height) - top },
  }
}
