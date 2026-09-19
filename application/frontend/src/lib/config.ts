import type { CameraKind, CameraSource } from "@/lib/types"

const DEFAULT_BACKEND_URL = "http://localhost:8000"

/** Backend origin without a trailing slash. */
export const BACKEND_URL = (process.env.NEXT_PUBLIC_BACKEND_URL ?? DEFAULT_BACKEND_URL).replace(/\/+$/, "")

/** Same origin over ws:// (or wss:// when the backend is https). */
const WS_BASE_URL = BACKEND_URL.replace(/^http/, "ws")

export const API = {
  health: `${BACKEND_URL}/api/health`,
  urdf: `${BACKEND_URL}/api/urdf`,
  linkage: `${BACKEND_URL}/api/linkage`,
  /** A `package://htn_description/meshes/<name>` visual of the URDF. */
  mesh: (name: string) => `${BACKEND_URL}/api/meshes/${encodeURIComponent(name)}`,
  iphone: `${BACKEND_URL}/api/iphone`,
} as const

export const WS = {
  state: `${WS_BASE_URL}/ws/state`,
  mirror: `${WS_BASE_URL}/ws/mirror`,
  camera: (source: CameraSource, kind: CameraKind) => `${WS_BASE_URL}/ws/camera/${source}/${kind}`,
} as const
