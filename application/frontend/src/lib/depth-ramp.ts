/**
 * The backend's depth palette (backend/app/depth.py `Colorizer.RAMP_RGB`): evenly spaced
 * stops, far -> near, linearly interpolated. Pixels with no reading are the page colour.
 */
const RAMP_FAR_TO_NEAR = [
  [0x2f, 0x4a, 0x63],
  [0x7f, 0x9b, 0xb3],
  [0xd9, 0xdd, 0xe0],
  [0xe9, 0xc9, 0xa8],
  [0xc2, 0x41, 0x0c],
] as const

const VOID_RGB = [0xf6, 0xf6, 0xf6] as const
/** JPEG noise around the void colour; the nearest ramp colour is 45 away. */
const VOID_TOLERANCE = 14

type Rgb = readonly [number, number, number]

export const DEPTH_GRADIENT = `linear-gradient(to bottom, ${RAMP_FAR_TO_NEAR.map(([r, g, b]) => `rgb(${r} ${g} ${b})`).join(", ")})`

function distanceSq(a: Rgb, b: Rgb): number {
  return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2
}

/**
 * Inverts the colormap: 0 = far end .. 1 = near end of the range, or null for a void
 * pixel. It projects the colour onto the ramp, so JPEG noise costs a few centimetres.
 */
export function nearnessOf(color: Rgb): number | null {
  if (distanceSq(color, VOID_RGB) < VOID_TOLERANCE ** 2) return null
  const segments = RAMP_FAR_TO_NEAR.length - 1
  let best = { distance: Number.POSITIVE_INFINITY, nearness: 0 }
  for (let i = 0; i < segments; i++) {
    const from = RAMP_FAR_TO_NEAR[i]
    const to = RAMP_FAR_TO_NEAR[i + 1]
    const along = from.map((channel, c) => to[c] - channel)
    const lengthSq = along[0] ** 2 + along[1] ** 2 + along[2] ** 2
    const dot = along.reduce((sum, step, c) => sum + step * (color[c] - from[c]), 0)
    const t = Math.min(1, Math.max(0, dot / lengthSq))
    const distance = distanceSq(color, [from[0] + along[0] * t, from[1] + along[1] * t, from[2] + along[2] * t])
    if (distance < best.distance) best = { distance, nearness: (i + t) / segments }
  }
  return best.nearness
}
