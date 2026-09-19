import { FINGERS } from "@/lib/types"

const WIDTH = FINGERS.length

/**
 * Fixed-capacity ring buffer of per-finger samples. Plain typed arrays, no
 * allocation per push, and no React involvement: read it on your own clock
 * (a throttled snapshot or requestAnimationFrame).
 */
export class FingerHistory {
  readonly capacity: number
  private readonly times: Float64Array
  private readonly values: Float32Array
  private head = 0
  private count = 0

  constructor(capacity: number) {
    this.capacity = capacity
    this.times = new Float64Array(capacity)
    this.values = new Float32Array(capacity * WIDTH)
  }

  /** Number of samples currently held (<= capacity). */
  get length(): number {
    return this.count
  }

  /** Append one sample: `t` in seconds, `state` in finger order. */
  push(t: number, state: ArrayLike<number>): void {
    this.times[this.head] = t
    const base = this.head * WIDTH
    for (let f = 0; f < WIDTH; f++) this.values[base + f] = state[f] ?? 0
    this.head = (this.head + 1) % this.capacity
    if (this.count < this.capacity) this.count++
  }

  /**
   * Copy one finger's samples into `out`, oldest first. If `out` is shorter
   * than the history, the newest `out.length` samples are kept.
   * @returns how many samples were written.
   */
  read(finger: number, out: Float32Array): number {
    return this.copy(out, (slot) => this.values[slot * WIDTH + finger])
  }

  /** Copy the sample timestamps (seconds) into `out`; same ordering as `read`. */
  readTimes(out: Float64Array): number {
    return this.copy(out, (slot) => this.times[slot])
  }

  clear(): void {
    this.head = 0
    this.count = 0
  }

  private copy(out: Float32Array | Float64Array, at: (slot: number) => number): number {
    const n = Math.min(this.count, out.length)
    const start = this.head - n + this.capacity
    for (let i = 0; i < n; i++) out[i] = at((start + i) % this.capacity)
    return n
  }
}
