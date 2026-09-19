import { useCallback, useEffect, useRef, useState, type RefObject } from "react"

import { WS } from "@/lib/config"
import { backoffDelay, closeQuietly } from "@/lib/socket"
import type { MirrorPose, MirrorStatus } from "@/lib/types"

/**
 * camera     - waiting for the webcam (permission prompt)
 * no-camera  - no webcam, permission denied, or the page is not a secure context
 * connecting - webcam open, socket not yet
 * busy       - another controller holds /ws/mirror; retrying
 * open       - frames go out, statuses come back
 */
export type MirrorLink = "camera" | "no-camera" | "connecting" | "busy" | "open"

/** What React renders from; the per-frame values go to `onFrame` instead. */
export type MirrorSummary = Pick<MirrorStatus, "mode" | "calibrated" | "capturing" | "error"> & {
  /** Pose the guided calibration asks for next; null once both are captured. */
  step: MirrorPose | null
}

const FRAME_WIDTH = 320
const FRAME_HEIGHT = 240
const FRAME_INTERVAL_MS = 33
const JPEG_QUALITY = 0.7
const BUSY_CODE = 1013
const IDLE: MirrorSummary = { mode: "off", calibrated: false, capturing: null, error: null, step: "fist" }

export interface Mirror {
  /** Attach to a muted, autoplaying <video>: the local webcam. */
  videoRef: RefObject<HTMLVideoElement | null>
  link: MirrorLink
  summary: MirrorSummary
  calibrate: (pose: MirrorPose) => void
  /** Start the guided calibration again; the hand keeps following until the first capture. */
  recalibrate: () => void
}

function isMirrorStatus(value: unknown): value is MirrorStatus {
  return typeof value === "object" && value !== null && typeof (value as Partial<MirrorStatus>).mode === "string"
}

/**
 * Webcam -> 320x240 JPEG -> /ws/mirror while mounted. `onFrame` runs for every status (30 Hz):
 * draw from it directly, never through React state.
 */
export function useMirror(onFrame: (status: MirrorStatus) => void): Mirror {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const socketRef = useRef<WebSocket | null>(null)
  const onFrameRef = useRef(onFrame)
  const stepRef = useRef<MirrorPose | null>("fist")
  const [link, setLink] = useState<MirrorLink>("camera")
  const [summary, setSummary] = useState<MirrorSummary>(IDLE)

  useEffect(() => {
    onFrameRef.current = onFrame
  }, [onFrame])

  useEffect(() => {
    let disposed = false
    let stream: MediaStream | null = null
    let retryTimer: ReturnType<typeof setTimeout> | null = null
    let frameTimer: ReturnType<typeof setInterval> | null = null
    let attempt = 0
    let encoding = false
    let wasCapturing: MirrorPose | null = null
    const canvas = document.createElement("canvas")
    canvas.width = FRAME_WIDTH
    canvas.height = FRAME_HEIGHT
    const context = canvas.getContext("2d")

    const sendFrame = () => {
      const socket = socketRef.current
      const video = videoRef.current
      // A frame still in the socket's buffer means the link is behind: skip, never queue.
      if (!socket || socket.readyState !== WebSocket.OPEN || socket.bufferedAmount > 0) return
      if (!video || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA || !context || encoding) return
      context.drawImage(video, 0, 0, FRAME_WIDTH, FRAME_HEIGHT)
      encoding = true
      canvas.toBlob(
        (blob) => {
          encoding = false
          if (blob && socket.readyState === WebSocket.OPEN) socket.send(blob)
        },
        "image/jpeg",
        JPEG_QUALITY,
      )
    }

    const open = () => {
      const socket = new WebSocket(WS.mirror)
      socketRef.current = socket
      socket.onopen = () => {
        attempt = 0
        setLink("open")
      }
      socket.onmessage = (event) => {
        if (typeof event.data !== "string") return
        let status: unknown
        try {
          status = JSON.parse(event.data)
        } catch {
          return
        }
        if (!isMirrorStatus(status)) return
        onFrameRef.current(status)
        const { mode, calibrated, capturing, error } = status
        // A failed capture starts over: the backend drops both poses when the range is refused.
        if (wasCapturing && !capturing) stepRef.current = error ? "fist" : wasCapturing === "fist" ? "open" : null
        wasCapturing = capturing
        const next = stepRef.current
        setSummary((prev) =>
          prev.mode === mode &&
          prev.calibrated === calibrated &&
          prev.capturing === capturing &&
          prev.error === error &&
          prev.step === next
            ? prev
            : { mode, calibrated, capturing, error, step: next },
        )
      }
      socket.onclose = (event) => {
        socketRef.current = null
        stepRef.current = "fist"
        wasCapturing = null
        setSummary(IDLE) // a new connection is a new session: the calibration is gone
        setLink(event.code === BUSY_CODE ? "busy" : "connecting")
        retryTimer = setTimeout(open, backoffDelay(attempt++))
      }
    }

    // Undefined outside a secure context (http:// on anything but localhost).
    const request = navigator.mediaDevices?.getUserMedia({ video: { width: FRAME_WIDTH * 2, height: FRAME_HEIGHT * 2 } })
    ;(request ?? Promise.reject(new Error("insecure context")))
      .then((media) => {
        if (disposed) {
          media.getTracks().forEach((track) => track.stop())
          return
        }
        stream = media
        if (videoRef.current) videoRef.current.srcObject = media
        setLink("connecting")
        open()
        frameTimer = setInterval(sendFrame, FRAME_INTERVAL_MS)
      })
      .catch(() => {
        if (!disposed) setLink("no-camera")
      })

    return () => {
      disposed = true
      if (retryTimer !== null) clearTimeout(retryTimer)
      if (frameTimer !== null) clearInterval(frameTimer)
      if (socketRef.current) closeQuietly(socketRef.current)
      socketRef.current = null
      stream?.getTracks().forEach((track) => track.stop())
    }
  }, [])

  const calibrate = useCallback((pose: MirrorPose) => {
    const socket = socketRef.current
    if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "calibrate", pose }))
  }, [])

  const recalibrate = useCallback(() => {
    stepRef.current = "fist"
    setSummary((prev) => ({ ...prev, step: "fist" }))
  }, [])

  return { videoRef, link, summary, calibrate, recalibrate }
}
