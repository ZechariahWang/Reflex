import { useEffect } from "react"
import { create } from "zustand"

import { API } from "@/lib/config"
import type { HealthResponse } from "@/lib/types"

const POLL_MS = 2000
const TIMEOUT_MS = 1500

export interface HealthState {
  /** Last successful response; kept while the API is unreachable. */
  health: HealthResponse | null
  /** null until the first poll settles. */
  reachable: boolean | null
}

const useHealthStore = create<HealthState>()(() => ({ health: null, reachable: null }))

let users = 0
let timer: ReturnType<typeof setInterval> | null = null

async function poll(): Promise<void> {
  try {
    const response = await fetch(API.health, { cache: "no-store", signal: AbortSignal.timeout(TIMEOUT_MS) })
    if (!response.ok) throw new Error(`health ${response.status}`)
    const health = (await response.json()) as HealthResponse
    if (users > 0) useHealthStore.setState({ health, reachable: true })
  } catch {
    if (users > 0) useHealthStore.setState({ reachable: false })
  }
}

/** GET /api/health every 2 s; one shared poller however many components use it. */
export function useHealth(): HealthState {
  useEffect(() => {
    if (users++ === 0) {
      void poll()
      timer = setInterval(() => void poll(), POLL_MS)
    }
    return () => {
      if (--users > 0) return
      if (timer !== null) clearInterval(timer)
      timer = null
    }
  }, [])

  return useHealthStore()
}
