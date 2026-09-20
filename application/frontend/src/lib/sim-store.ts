import { useEffect } from "react"
import { create } from "zustand"

import { WS } from "@/lib/config"
import { FingerHistory } from "@/lib/finger-history"
import { backoffDelay, closeQuietly } from "@/lib/socket"
import { FINGERS, type CommandMessage, type FingerValues, type EpisodeSession, type StateMessage, type TrackedObject } from "@/lib/types"

/** Rate of /ws/state. */
export const STATE_HZ = 60
/** Span of the per-finger history. */
export const HISTORY_SECONDS = 10
/** Samples held per finger. */
export const HISTORY_CAPACITY = STATE_HZ * HISTORY_SECONDS
/** Rate at which `snapshot` (the React-facing copy of the state) updates. */
export const SNAPSHOT_HZ = 10

export type ConnectionStatus = "connecting" | "open" | "closed"

/**
 * Full-rate data. This object is created once and mutated in place at 30 Hz,
 * so it never notifies subscribers: read it with `useSimStore.getState().live`
 * from `useFrame` / requestAnimationFrame, never through a React selector.
 */
export interface LiveData {
  /** Latest /ws/state message; keeps its last value while disconnected. */
  message: StateMessage | null
  /** `performance.now()` when `message` arrived. */
  receivedAt: number
  /** Last ~10 s of `state` per finger. */
  history: FingerHistory
}

export interface SimStore {
  /** State of the browser <-> backend socket. */
  status: ConnectionStatus
  /** Latest message, republished at most SNAPSHOT_HZ times a second. Safe to select in React. */
  snapshot: StateMessage | null
  live: LiveData
  /**
   * Publish a target to /hand/command: exactly five values in finger order,
   * clamped to 0..1. Returns false if the input is malformed or the socket is down.
   */
  sendCommand: (data: number[]) => boolean
  /** Ask the HAL for backdrive mode (torque off) or back; the result shows up as `snapshot.passive`. */
  setPassive: (passive: boolean) => boolean
}

let socket: WebSocket | null = null
let retryTimer: ReturnType<typeof setTimeout> | null = null
let attempt = 0
let users = 0
let lastPublish = 0

export const useSimStore = create<SimStore>()(() => ({
  status: "connecting",
  snapshot: null,
  live: { message: null, receivedAt: 0, history: new FingerHistory(HISTORY_CAPACITY) },
  sendCommand: (data) => {
    if (data.length !== FINGERS.length || !data.every(Number.isFinite)) return false
    if (socket?.readyState !== WebSocket.OPEN) return false
    const clamped = data.map((v) => Math.min(1, Math.max(0, v))) as FingerValues
    const message: CommandMessage = { type: "command", data: clamped }
    socket.send(JSON.stringify(message))
    return true
  },
  setPassive: (passive) => {
    if (socket?.readyState !== WebSocket.OPEN) return false
    socket.send(JSON.stringify({ type: "passive", data: passive }))
    return true
  },
}))

function isStateMessage(value: unknown): value is StateMessage {
  if (typeof value !== "object" || value === null) return false
  const candidate = value as Partial<StateMessage>
  return (
    typeof candidate.t === "number" &&
    Array.isArray(candidate.state) &&
    candidate.state.length === FINGERS.length &&
    typeof candidate.joints === "object" &&
    candidate.joints !== null &&
    Array.isArray(candidate.objects)
  )
}

function handleMessage(event: MessageEvent): void {
  if (typeof event.data !== "string") return
  let message: unknown
  try {
    message = JSON.parse(event.data)
  } catch {
    return
  }
  if (!isStateMessage(message)) return

  const { live, snapshot } = useSimStore.getState()
  // Every message parses into a new `objects` array: keep the old one while nothing changed, or
  // whoever selects it (the hand viewport) renders again for every snapshot, objects or none.
  if (snapshot && JSON.stringify(snapshot.objects) === JSON.stringify(message.objects)) message.objects = snapshot.objects
  const now = performance.now()
  live.message = message
  live.receivedAt = now
  live.history.push(message.t, message.state)

  const rosFlipped = snapshot?.ros_connected !== message.ros_connected
  if (rosFlipped || now - lastPublish >= 1000 / SNAPSHOT_HZ) {
    lastPublish = now
    useSimStore.setState({ snapshot: message })
  }
}

function open(): void {
  const ws = new WebSocket(WS.state)
  socket = ws
  ws.onopen = () => {
    attempt = 0
    useSimStore.setState({ status: "open" })
  }
  ws.onmessage = handleMessage
  ws.onclose = () => {
    socket = null
    useSimStore.setState({ status: "closed" })
    retryTimer = setTimeout(() => {
      retryTimer = null
      useSimStore.setState({ status: "connecting" })
      open()
    }, backoffDelay(attempt++))
  }
}

function acquire(): void {
  if (users++ === 0) open()
}

function release(): void {
  if (--users > 0) return
  if (retryTimer !== null) clearTimeout(retryTimer)
  retryTimer = null
  attempt = 0
  if (socket) closeQuietly(socket)
  socket = null
  useSimStore.setState({ status: "connecting" })
}

/**
 * Keeps the /ws/state socket open while the calling component is mounted
 * (reference-counted; reconnects forever with backoff). Mounted once by
 * <Providers>, so components only ever read the store.
 */
export function useSimConnection(): void {
  useEffect(() => {
    acquire()
    return release
  }, [])
}

export const selectStatus = (s: SimStore): ConnectionStatus => s.status
export const selectSnapshot = (s: SimStore): StateMessage | null => s.snapshot
export const selectPassive = (s: SimStore): boolean => s.snapshot?.passive ?? false
const NO_OBJECTS: TrackedObject[] = []
export const selectObjects = (s: SimStore): TrackedObject[] => s.snapshot?.objects ?? NO_OBJECTS
/** Which objects exist, as one string: components that key children by id re-render only when the set changes. */
export const selectObjectIds = (s: SimStore): string => (s.snapshot?.objects ?? NO_OBJECTS).map((o) => o.id).join(",")
const IDLE: EpisodeSession = { mode: "idle" }
export const selectSessionMode = (s: SimStore): EpisodeSession["mode"] => (s.snapshot?.session ?? IDLE).mode
export const selectSession = (s: SimStore): EpisodeSession => s.snapshot?.session ?? IDLE
export const selectRosConnected = (s: SimStore): boolean => s.snapshot?.ros_connected ?? false
/** Socket open and ROS reachable: hand data is flowing. */
export const selectIsLive = (s: SimStore): boolean => s.status === "open" && selectRosConnected(s)
