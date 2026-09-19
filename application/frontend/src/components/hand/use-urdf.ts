import { useEffect, useState } from "react"

import { API } from "@/lib/config"
import { backoffDelay } from "@/lib/socket"

export interface UrdfDocument {
  xml: string
  name: string
  linkCount: number
  jointCount: number
}

/** Null unless the text is a URDF with at least one link. */
function inspect(xml: string): UrdfDocument | null {
  const robot = new DOMParser().parseFromString(xml, "text/xml").querySelector("robot")
  if (!robot) return null
  const count = (tag: string) => Array.from(robot.children).filter((node) => node.nodeName === tag).length
  const linkCount = count("link")
  if (linkCount === 0) return null
  return { xml, name: robot.getAttribute("name") ?? "robot", linkCount, jointCount: count("joint") }
}

/**
 * The robot description from the backend. `/api/urdf` answers 503 until ROS has
 * delivered one, so this keeps retrying with backoff until it has a valid document.
 */
export function useUrdf(): UrdfDocument | null {
  const [document, setDocument] = useState<UrdfDocument | null>(null)

  useEffect(() => {
    const abort = new AbortController()
    let timer: ReturnType<typeof setTimeout> | null = null
    let attempt = 0

    const load = async () => {
      try {
        const response = await fetch(API.urdf, { signal: abort.signal, cache: "no-store" })
        const parsed = response.ok ? inspect(await response.text()) : null
        if (parsed) {
          setDocument(parsed)
          return
        }
      } catch {
        // Backend unreachable or the request was aborted; both fall through.
      }
      if (!abort.signal.aborted) timer = setTimeout(load, backoffDelay(attempt++))
    }
    void load()

    return () => {
      abort.abort()
      if (timer !== null) clearTimeout(timer)
    }
  }, [])

  return document
}
