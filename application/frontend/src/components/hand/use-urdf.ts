import { useEffect, useState } from "react"
import type { BufferGeometry } from "three"
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js"
import { mergeVertices, toCreasedNormals } from "three/examples/jsm/utils/BufferGeometryUtils.js"

import { API } from "@/lib/config"
import { backoffDelay } from "@/lib/socket"

import type { HandLinkage } from "./linkage"

/** Everything the viewer needs to build the hand; complete, or not there at all. */
export interface HandDescription {
  xml: string
  name: string
  linkCount: number
  jointCount: number
  /** Visual meshes by URDF filename (`package://.../x.stl`), in millimetres as exported from CAD. */
  meshes: Map<string, BufferGeometry>
  /** Null for a hand without linkages (every part then hangs on a driven joint). */
  linkage: HandLinkage | null
}

const PARALLEL_DOWNLOADS = 8
/** STL is flat-shaded triangle soup; below this angle neighbouring faces are one smooth surface. */
const CREASE_ANGLE = (35 * Math.PI) / 180

/** Null unless the text is a URDF with at least one link. */
function inspect(xml: string) {
  const robot = new DOMParser().parseFromString(xml, "text/xml").querySelector("robot")
  if (!robot) return null
  const count = (tag: string) => Array.from(robot.children).filter((node) => node.nodeName === tag).length
  const linkCount = count("link")
  if (linkCount === 0) return null
  const files = new Set<string>()
  // Visuals only: a collision mesh is never drawn.
  robot.querySelectorAll("visual mesh[filename]").forEach((node) => files.add(node.getAttribute("filename")!))
  return { xml, name: robot.getAttribute("name") ?? "robot", linkCount, jointCount: count("joint"), files: [...files] }
}

async function fetchMeshes(files: string[], signal: AbortSignal): Promise<Map<string, BufferGeometry>> {
  const loader = new STLLoader()
  const meshes = new Map<string, BufferGeometry>()
  const queue = [...files]
  const worker = async () => {
    for (let file = queue.pop(); file !== undefined; file = queue.pop()) {
      const response = await fetch(API.mesh(file.split("/").pop() ?? file), { signal })
      if (!response.ok) throw new Error(`mesh ${file}: ${response.status}`)
      const soup = loader.parse(await response.arrayBuffer())
      soup.deleteAttribute("normal")
      const welded = mergeVertices(soup, 1e-3)
      meshes.set(file, toCreasedNormals(welded, CREASE_ANGLE))
      soup.dispose()
      welded.dispose()
    }
  }
  await Promise.all(Array.from({ length: PARALLEL_DOWNLOADS }, worker))
  return meshes
}

async function fetchLinkage(signal: AbortSignal): Promise<HandLinkage | null> {
  const response = await fetch(API.linkage, { signal, cache: "no-store" })
  return response.ok ? ((await response.json()) as HandLinkage) : null
}

/**
 * The robot description from the backend: URDF, its meshes and the linkage geometry.
 * `/api/urdf` answers 503 until ROS has delivered one, so this keeps retrying with backoff
 * until all of it is there; a hand built from part of it would be missing fingers.
 */
export function useUrdf(): HandDescription | null {
  const [description, setDescription] = useState<HandDescription | null>(null)

  useEffect(() => {
    const abort = new AbortController()
    let timer: ReturnType<typeof setTimeout> | null = null
    let attempt = 0

    const load = async () => {
      try {
        const response = await fetch(API.urdf, { signal: abort.signal, cache: "no-store" })
        const parsed = response.ok ? inspect(await response.text()) : null
        if (parsed) {
          const { files, ...document } = parsed
          const [meshes, linkage] = await Promise.all([fetchMeshes(files, abort.signal), fetchLinkage(abort.signal)])
          if (!abort.signal.aborted) setDescription({ ...document, meshes, linkage })
          return
        }
      } catch {
        // Backend unreachable, a mesh missing, or the request was aborted: all fall through.
      }
      if (!abort.signal.aborted) timer = setTimeout(load, backoffDelay(attempt++))
    }
    void load()

    return () => {
      abort.abort()
      if (timer !== null) clearTimeout(timer)
    }
  }, [])

  return description
}
