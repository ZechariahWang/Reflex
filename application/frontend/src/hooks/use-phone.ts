import { useEffect } from "react"
import { create } from "zustand"

import { API } from "@/lib/config"
import type { PhoneStatus } from "@/lib/types"

const POLL_MS = 2000
const TIMEOUT_MS = 1500
const STORAGE_KEY = "htn.iphone.host"

export interface PhoneState {
  /** null until the backend has answered once. */
  phone: PhoneStatus | null
  /** Set when the last connect() was rejected (e.g. a malformed address). */
  error: string | null
}

const usePhoneStore = create<PhoneState>()(() => ({ phone: null, error: null }))

let users = 0
let timer: ReturnType<typeof setInterval> | null = null
let restored = false

function remembered(): string {
  try {
    return window.localStorage.getItem(STORAGE_KEY) ?? ""
  } catch {
    return ""
  }
}

/** Turn the phone's image a quarter clockwise (portrait sensor -> landscape, or the other way up). */
export async function rotatePhone(): Promise<void> {
  const current = usePhoneStore.getState().phone?.rotation ?? 0
  await post({ rotation: (current + 90) % 360 }, null)
}

/** Point the backend's Record3D client at `host` ("" disconnects) and remember it for next time. */
export async function connectPhone(host: string): Promise<void> {
  await post({ host }, host.trim())
}

async function post(body: { host: string } | { rotation: number }, remember: string | null): Promise<void> {
  try {
    const response = await fetch(API.iphone, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(TIMEOUT_MS * 4),
    })
    if (!response.ok) {
      const body = (await response.json().catch(() => null)) as { detail?: unknown } | null
      usePhoneStore.setState({ error: typeof body?.detail === "string" ? body.detail : `rejected (${response.status})` })
      return
    }
    try {
      if (remember !== null) window.localStorage.setItem(STORAGE_KEY, remember)
    } catch {
      // Storage blocked: the address just is not remembered.
    }
    usePhoneStore.setState({ phone: (await response.json()) as PhoneStatus, error: null })
  } catch {
    usePhoneStore.setState({ error: "backend unreachable" })
  }
}

async function poll(): Promise<void> {
  try {
    const response = await fetch(API.iphone, { cache: "no-store", signal: AbortSignal.timeout(TIMEOUT_MS) })
    if (!response.ok) throw new Error(`iphone ${response.status}`)
    const phone = (await response.json()) as PhoneStatus
    if (users > 0) usePhoneStore.setState({ phone })
    // A restarted backend has forgotten the phone: hand it the remembered address once.
    if (!restored && phone.host === "" && remembered() !== "") {
      restored = true
      void connectPhone(remembered())
    }
  } catch {
    if (users > 0) usePhoneStore.setState({ phone: null })
  }
}

/** GET /api/iphone every 2 s; one shared poller however many components use it. */
export function usePhone(): PhoneState {
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

  return usePhoneStore()
}
