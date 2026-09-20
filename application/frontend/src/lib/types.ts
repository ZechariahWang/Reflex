/** Finger order used by every array in the system. */
export const FINGERS = ["thumb", "index", "middle", "ring", "pinky"] as const

export type Finger = (typeof FINGERS)[number]
export type JointName = `${Finger}_joint`
export type LinkName = `${Finger}_finger`

/** Joint travel in radians: 0 = open, JOINT_MAX_RAD = closed. */
export const JOINT_MAX_RAD = 1.57

/** Five values in finger order, each 0 (open) .. 1 (closed). */
export type FingerValues = [number, number, number, number, number]

export type TopicKey = "joint_states" | "hand_state" | "hand_command" | "color" | "depth" | "iphone" | "objects"

/** ROS topic behind each key, for labels and tags. */
export const TOPIC_NAMES: Record<TopicKey, string> = {
  joint_states: "/joint_states",
  hand_state: "/hand/state",
  hand_command: "/hand/command",
  color: "/camera/color/image_raw/compressed",
  depth: "/camera/aligned_depth_to_color/image_raw/compressedDepth",
  iphone: "/head_camera/color/image_raw/compressed",
  objects: "detector",
}

/**
 * One object tracked around the hand, in the wrist camera's frame (`camera_link`: x forward,
 * y left, z up), metres. The camera is fixed to the hand, so this is a position relative to it.
 */
export interface TrackedObject {
  id: number
  label: string
  xyz: [number, number, number]
  /** Extent on the same axes. */
  size: [number, number, number]
  confidence: number
  /** Seconds since the last detection; grows while the object is remembered out of view. */
  age: number
  /** Detections so far. */
  hits: number
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
  /**
   * Which way the real hand points: base_link as a quaternion (x, y, z, w) in a world with z up,
   * from the wrist camera's IMU. Yaw 0 = where it pointed at the start. null without an IMU.
   */
  orientation?: [number, number, number, number] | null
  /** The surroundings: objects the backend currently tracks (empty without a detector). */
  objects: TrackedObject[]
  rates: TopicRates
}

/** Client -> server on /ws/state. */
export interface CommandMessage {
  type: "command"
  data: FingerValues
}

/** Both come through ROS; iphone is the head camera (`/head_camera`) and has colour only. */
export type CameraSource = "realsense" | "iphone"
export type CameraKind = "color" | "depth"

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

export type MirrorMode = "off" | "no_hand" | "following"
export type MirrorPose = "open" | "fist"

/** One /ws/mirror status message: what the backend made of the last webcam frame. */
export interface MirrorStatus {
  mode: MirrorMode
  calibrated: boolean
  /** Pose being captured right now. */
  capturing: MirrorPose | null
  /** Why the last capture failed: "no_hand" or "range". */
  error: string | null
  /** The controller's curls, filtered; null without a calibration or a hand. */
  controller: FingerValues | null
  /** What the mirror holds or sends on /hand/command; null while off. */
  command: FingerValues | null
  /** 21 image points, x and y in 0..1; null without a hand. */
  landmarks: [number, number][] | null
}
