/** Finger order used by every array in the system. */
export const FINGERS = ["thumb", "index", "middle", "ring", "pinky"] as const

export type Finger = (typeof FINGERS)[number]
export type JointName = `${Finger}_joint`
export type LinkName = `${Finger}_finger`

/** Joint travel in radians: 0 = open, JOINT_MAX_RAD = closed. */
export const JOINT_MAX_RAD = 1.57

/** Five values in finger order, each 0 (open) .. 1 (closed). */
export type FingerValues = [number, number, number, number, number]

export type TopicKey = "joint_states" | "hand_state" | "hand_command" | "color" | "depth" | "iphone"

/** ROS topic behind each key, for labels and tags. */
export const TOPIC_NAMES: Record<TopicKey, string> = {
  joint_states: "/joint_states",
  hand_state: "/hand/state",
  hand_command: "/hand/command",
  color: "/camera/color/image_raw/compressed",
  depth: "/camera/aligned_depth_to_color/image_raw/compressedDepth",
  iphone: "record3d wi-fi stream",
}

/** Messages per second received from ROS, per topic. */
export type TopicRates = Record<TopicKey, number>

/** Server -> client on /ws/state, 60 Hz. */
export interface StateMessage {
  /** Unix time in seconds. */
  t: number
  ros_connected: boolean
  fingers: Finger[]
  /** Radians by joint name. */
  joints: Record<JointName, number>
  /** Measured position, finger order. */
  state: FingerValues
  /** Last commanded target, finger order; null until one is published. */
  command: FingerValues | null
  /** Backdrive mode: the HAL has the torque off, a person moves the fingers, commands are ignored. */
  passive: boolean
  rates: TopicRates
}

/** Client -> server on /ws/state. */
export interface CommandMessage {
  type: "command"
  data: FingerValues
}

/** realsense comes through ROS; iphone is the Record3D app's Wi-Fi stream, read by the backend. */
export type CameraSource = "realsense" | "iphone"
export type CameraKind = "color" | "depth"

/** GET / POST /api/iphone. */
export interface PhoneStatus {
  /** Address the backend is pointed at; "" = none. */
  host: string
  state: "off" | "connecting" | "streaming" | "error"
  /** Why `state` is "error". */
  detail: string
  /** Degrees the image is turned clockwise; the sensor is portrait, 90 / 270 show it landscape. */
  rotation: 0 | 90 | 180 | 270
}

/** JSON text frame on /ws/camera/*; binary frames on the same socket are JPEGs. */
export interface CameraMeta {
  type: "meta"
  width: number
  height: number
  hz: number
  /** false = no frame received from ROS in the last 2 s. */
  available: boolean
  /** Depth only: colormap range in millimetres. */
  min_mm?: number
  max_mm?: number
}

export interface TopicHealth {
  hz: number
  /** Milliseconds since the last message; null if none ever arrived. */
  age_ms: number | null
}

/** GET /api/health */
export interface HealthResponse {
  ros_connected: boolean
  mock: boolean
  rosbridge_url: string
  topics: Record<TopicKey, TopicHealth>
}
