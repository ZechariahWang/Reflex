/**
 * Kinematics of one finger's linkage, a port of `htn_control/linkage.py` (same names, same maths).
 *
 * The URDF is a tree, the real mechanism has loops. Only `<finger>_joint` (the servo horn) is
 * driven; the six passive joints of a finger follow from it, and this works them out. ROS
 * publishes them for the measured hand, but nobody publishes them for the commanded ghost, so
 * the viewer solves both itself and never shows a half-updated mechanism.
 */
import type { Finger } from "@/lib/types"

type Point = readonly [number, number]

type PivotName = "G0" | "G1" | "G2" | "P" | "A" | "B" | "M" | "E" | "T" | "U"

/** Passive joints of a finger, in the order `solve` returns their angles: `<finger>_<role>_joint`. */
export const PASSIVE_ROLES = ["rod", "triangle", "ternary", "long", "binary", "adapter"] as const
export type PassiveAngles = [number, number, number, number, number, number]

/** One finger's entry of `GET /api/linkage` (config/linkage.yaml): millimetres, in the linkage plane. */
export interface FingerLinkage {
  axis: "x" | "z"
  plane: number
  /** Sense of horn rotation about +axis that closes the finger. */
  closing: 1 | -1
  pivots: Record<PivotName, Point>
  closed_rad: number
  lock_rad: number
}
export type HandLinkage = Record<Finger, FingerLinkage>

const SAMPLES = 181

const sub = (a: Point, b: Point): Point => [a[0] - b[0], a[1] - b[1]]
const dist = (a: Point, b: Point) => Math.hypot(a[0] - b[0], a[1] - b[1])
const angle = (v: Point) => Math.atan2(v[1], v[0])
const wrap = (a: number) => ((((a + Math.PI) % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI)) - Math.PI

function about(centre: Point, point: Point, a: number): Point {
  const [x, y] = sub(point, centre)
  const c = Math.cos(a)
  const s = Math.sin(a)
  return [centre[0] + c * x - s * y, centre[1] + s * x + c * y]
}

/** The intersection of two circles that is closest to `near`, or null if they miss. */
function circles(c1: Point, r1: number, c2: Point, r2: number, near: Point): Point | null {
  const d = dist(c1, c2)
  if (d === 0 || d > r1 + r2 || d < Math.abs(r1 - r2)) return null
  const a = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
  const h = Math.sqrt(Math.max(r1 * r1 - a * a, 0))
  const ux = (c2[0] - c1[0]) / d
  const uy = (c2[1] - c1[1]) / d
  const mx = c1[0] + a * ux
  const my = c1[1] + a * uy
  const first: Point = [mx - h * uy, my + h * ux]
  const second: Point = [mx + h * uy, my - h * ux]
  return dist(first, near) <= dist(second, near) ? first : second
}

interface Assembly {
  A: Point
  M: Point
  U: Point
  angles: PassiveAngles
}

/** Passive joint angles for an absolute horn rotation; `near` keeps each four-bar on its own assembly. */
function assemble(p: Record<PivotName, Point>, horn: number, near: Pick<Assembly, "A" | "M" | "U">): Assembly | null {
  const length = (a: PivotName, b: PivotName) => dist(p[a], p[b])
  const P = about(p.G0, p.P, horn)
  const A = circles(P, length("P", "A"), p.G1, length("G1", "A"), near.A)
  if (!A) return null
  const triangle = wrap(angle(sub(A, p.G1)) - angle(sub(p.A, p.G1)))
  const B = about(p.G1, p.B, triangle)
  const M = circles(B, length("B", "M"), p.G2, length("G2", "M"), near.M)
  if (!M) return null
  const long = wrap(angle(sub(M, p.G2)) - angle(sub(p.M, p.G2)))
  const T = about(p.G2, p.T, long)
  const ternary = wrap(angle(sub(M, B)) - angle(sub(p.M, p.B)))
  const E = about(B, [B[0] + p.E[0] - p.B[0], B[1] + p.E[1] - p.B[1]], ternary)
  const U = circles(T, length("T", "U"), E, length("E", "U"), near.U)
  if (!U) return null
  const rod = wrap(angle(sub(A, P)) - angle(sub(p.A, p.P)))
  const binary = wrap(angle(sub(U, T)) - angle(sub(p.U, p.T)))
  const adapter = wrap(angle(sub(U, E)) - angle(sub(p.U, p.E)))
  // Child relative to its parent in the URDF tree: rod on the horn, ternary on the triangle,
  // binary on the long link, adapter on the ternary bar; triangle and long link hang on the base.
  return {
    A,
    M,
    U,
    angles: [wrap(rod - horn), triangle, wrap(ternary - triangle), long, wrap(binary - long), wrap(adapter - ternary)],
  }
}

/**
 * Lookup `q -> passive joint angles` over the driven joint's travel `[0, closed]` (q >= 0 closes,
 * whichever way the horn really turns). Built once per finger; a call is one interpolation.
 */
export function passiveJointSolver(linkage: FingerLinkage, closed: number): (q: number, out: PassiveAngles) => PassiveAngles {
  const rows: PassiveAngles[] = []
  let near: Pick<Assembly, "A" | "M" | "U"> = linkage.pivots
  for (let i = 0; i < SAMPLES; i++) {
    const solution = assemble(linkage.pivots, linkage.closing * closed * (i / (SAMPLES - 1)), near)
    // Past where the mechanism binds (a travel beyond lock_rad): hold the last pose that assembles.
    if (!solution) {
      rows.push(rows[rows.length - 1] ?? [0, 0, 0, 0, 0, 0])
      continue
    }
    near = solution
    const previous = rows[rows.length - 1]
    // Keep every column continuous: interpolating across a +-pi wrap would spin a part around.
    rows.push(previous ? (solution.angles.map((a, k) => previous[k] + wrap(a - previous[k])) as PassiveAngles) : solution.angles)
  }
  return (q, out) => {
    const x = Math.min(Math.max(closed > 0 ? q / closed : 0, 0), 1) * (SAMPLES - 1)
    const i = Math.min(Math.floor(x), SAMPLES - 2)
    const f = x - i
    for (let k = 0; k < out.length; k++) out[k] = rows[i][k] + (rows[i + 1][k] - rows[i][k]) * f
    return out
  }
}
