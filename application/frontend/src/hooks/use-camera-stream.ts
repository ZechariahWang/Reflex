import { useEffect, useRef, useState, type RefObject } from "react"

import { WS } from "@/lib/config"
import { backoffDelay, closeQuietly } from "@/lib/socket"
import type { CameraKind, CameraMeta, CameraSource } from "@/lib/types"

/**
 * connecting - socket not open yet
 * live       - frames are arriving
 * no-signal  - socket open, but no frame for NO_SIGNAL_MS (camera absent or ROS down)
 * offline    - backend unreachable; retrying with backoff
 */
export type CameraStreamStatus = "connecting" | "live" | "no-signal" | "offline"

export interface CameraStream {
  /** Attach to a <canvas>; its width/height follow the incoming frames. */
  canvasRef: RefObject<HTMLCanvasElement | null>
  /** Latest meta frame from the server; null until the first one. */
  meta: CameraMeta | null
  status: CameraStreamStatus
  /** Frames actually drawn per second, measured over the last second. */
  fps: number
}

const NO_SIGNAL_MS = 2000
const FPS_WINDOW_MS = 1000

function isCameraMeta(value: unknown): value is CameraMeta {
  return typeof value === "object" && value !== null && (value as Partial<CameraMeta>).type === "meta"
}

interface StreamState {
  /** Which stream these values belong to; anything else is a leftover from before a switch. */
  url: string
  meta: CameraMeta | null
  status: CameraStreamStatus
  fps: number
}

export function useCameraStream(source: CameraSource, kind: CameraKind): CameraStream {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const url = WS.camera(source, kind)
  const [state, setState] = useState<StreamState>({ url, meta: null, status: "connecting", fps: 0 })

  useEffect(() => {
    const update = (patch: Partial<Omit<StreamState, "url">>) =>
      setState((prev) => ({ ...(prev.url === url ? prev : { url, meta: null, status: "connecting", fps: 0 }), ...patch }))
    const setMeta = (meta: CameraMeta) => update({ meta })
    const setStatus = (status: CameraStreamStatus) => update({ status })
    const setFps = (fps: number) => update({ fps })

    let disposed = false
    let socket: WebSocket | null = null
    let retryTimer: ReturnType<typeof setTimeout> | null = null
    let attempt = 0
    let decoding = false
    let pending: Blob | null = null
    let drawn = 0
    let lastFrameAt = 0

    const draw = (bitmap: ImageBitmap) => {
      const canvas = canvasRef.current
      if (!canvas) return
      if (canvas.width !== bitmap.width || canvas.height !== bitmap.height) {
        canvas.width = bitmap.width
        canvas.height = bitmap.height
      }
      canvas.getContext("2d")?.drawImage(bitmap, 0, 0)
      drawn++
      lastFrameAt = performance.now()
      setStatus("live")
    }

    // One decode in flight at a time. Frames that arrive meanwhile overwrite
    // `pending`, so a slow decoder skips to the newest frame instead of queueing.
    const decode = async (blob: Blob) => {
      decoding = true
      for (let next: Blob | null = blob; next && !disposed; ) {
        try {
          const bitmap = await createImageBitmap(next)
          if (!disposed) draw(bitmap)
          bitmap.close()
        } catch {
          // A truncated or corrupt JPEG: skip it, the next frame replaces it.
        }
        next = pending
        pending = null
      }
      decoding = false
    }

    const handleMessage = (event: MessageEvent) => {
      if (typeof event.data === "string") {
        try {
          const parsed: unknown = JSON.parse(event.data)
          if (isCameraMeta(parsed)) setMeta(parsed)
        } catch {
          // Not JSON: ignore.
        }
      } else if (event.data instanceof Blob) {
        if (decoding) pending = event.data
        else void decode(event.data)
      }
    }

    const open = () => {
      const ws = new WebSocket(url)
      ws.binaryType = "blob"
      socket = ws
      ws.onopen = () => {
        attempt = 0
        lastFrameAt = performance.now()
      }
      ws.onmessage = handleMessage
      ws.onclose = () => {
        socket = null
        pending = null
        setStatus("offline")
        retryTimer = setTimeout(() => {
          setStatus("connecting")
          open()
        }, backoffDelay(attempt++))
      }
    }

    const meter = setInterval(() => {
      setFps(drawn)
      drawn = 0
      if (socket?.readyState === WebSocket.OPEN && performance.now() - lastFrameAt > NO_SIGNAL_MS) {
        setStatus("no-signal")
      }
    }, FPS_WINDOW_MS)

    open()

    return () => {
      disposed = true
      pending = null
      clearInterval(meter)
      if (retryTimer !== null) clearTimeout(retryTimer)
      if (socket) closeQuietly(socket)
    }
  }, [url])

  const current = state.url === url ? state : { meta: null, status: "connecting" as const, fps: 0 }
  return { canvasRef, meta: current.meta, status: current.status, fps: current.fps }
}
