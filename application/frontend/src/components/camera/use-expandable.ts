import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from "react"
import { animate, useMotionValue, useReducedMotion, type MotionValue } from "motion/react"

interface Box {
  top: number
  left: number
  width: number
  height: number
}

type BoxValues = { [K in keyof Box]: MotionValue<number | string> }

const KEYS = ["top", "left", "width", "height"] as const
const DOCKED: Record<keyof Box, number | string> = { top: 0, left: 0, width: "100%", height: "100%" }
const EASE = [0.22, 1, 0.36, 1] as const
const DURATION_S = 0.55
const INSET_PX = 12
const MIN_COVER_HEIGHT_PX = 320

function boxOf(element: Element): Box {
  const { top, left, width, height } = element.getBoundingClientRect()
  return { top, left, width, height }
}

/**
 * The area to cover: the top-level section of <main> that holds the slot (the
 * console's main row) plus the section under it (telemetry), so a 4:3 image gets
 * the height to fill the frame; the page footer stays visible. Clamped to the
 * viewport, and the whole viewport when that area is scrolled mostly out of view.
 */
function coverBox(slot: Element): Box {
  const viewport: Box = {
    top: INSET_PX,
    left: INSET_PX,
    width: window.innerWidth - 2 * INSET_PX,
    height: window.innerHeight - 2 * INSET_PX,
  }
  const main = slot.closest("main")
  let section: Element | null = slot
  while (section && section.parentElement !== main) section = section.parentElement
  if (!section) return viewport

  const row = boxOf(section)
  const below = section.nextElementSibling
  const last = below && below.tagName !== "FOOTER" ? boxOf(below) : row
  const top = Math.max(row.top, viewport.top)
  const bottom = Math.min(last.top + last.height, viewport.top + viewport.height)
  if (bottom - top < MIN_COVER_HEIGHT_PX) return viewport
  return { top, left: row.left, width: row.width, height: bottom - top }
}

export interface Expandable {
  /** Stays in the layout and keeps the panel's place while it floats. */
  slotRef: RefObject<HTMLDivElement | null>
  /** Bind to the floating element's `style`. */
  box: BoxValues
  /** True while the element is out of flow (expanded or flying back). */
  floating: boolean
  expanded: boolean
  toggle: () => void
  collapse: () => void
}

/**
 * Flies an element from its slot in the layout to cover the main area and
 * back. It animates real geometry instead of a transform, so the hairlines and
 * type inside stay undistorted and the canvas re-letterboxes on every frame.
 */
export function useExpandable(): Expandable {
  const slotRef = useRef<HTMLDivElement | null>(null)
  const top = useMotionValue<number | string>(DOCKED.top)
  const left = useMotionValue<number | string>(DOCKED.left)
  const width = useMotionValue<number | string>(DOCKED.width)
  const height = useMotionValue<number | string>(DOCKED.height)
  const box = useMemo<BoxValues>(() => ({ top, left, width, height }), [top, left, width, height])
  const expandedRef = useRef(false)
  const [expanded, setExpanded] = useState(false)
  const [floating, setFloating] = useState(false)
  const duration = useReducedMotion() ? 0 : DURATION_S

  const fly = useCallback(
    (to: Box, onComplete?: () => void) => {
      KEYS.forEach((key, i) =>
        animate(box[key], to[key], { duration, ease: EASE, onComplete: i === 0 ? onComplete : undefined }),
      )
    },
    [box, duration],
  )

  const expand = useCallback(() => {
    const slot = slotRef.current
    if (!slot) return
    const from = boxOf(slot)
    KEYS.forEach((key) => box[key].jump(from[key]))
    expandedRef.current = true
    setExpanded(true)
    setFloating(true)
    fly(coverBox(slot))
  }, [box, fly])

  const collapse = useCallback(() => {
    const slot = slotRef.current
    if (!slot || !expandedRef.current) return
    expandedRef.current = false
    setExpanded(false)
    fly(boxOf(slot), () => {
      if (expandedRef.current) return
      KEYS.forEach((key) => box[key].jump(DOCKED[key]))
      setFloating(false)
    })
  }, [box, fly])

  const toggle = useCallback(() => (expandedRef.current ? collapse() : expand()), [collapse, expand])

  useEffect(() => {
    if (!expanded) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") collapse()
    }
    const onResize = () => {
      const slot = slotRef.current
      if (!slot) return
      const cover = coverBox(slot)
      KEYS.forEach((key) => box[key].jump(cover[key]))
    }
    window.addEventListener("keydown", onKeyDown)
    window.addEventListener("resize", onResize)
    return () => {
      window.removeEventListener("keydown", onKeyDown)
      window.removeEventListener("resize", onResize)
    }
  }, [box, expanded, collapse])

  return { slotRef, box, floating, expanded, toggle, collapse }
}
