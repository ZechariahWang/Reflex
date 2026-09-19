import type { FingerValues } from "@/lib/types"

/**
 * Leading + trailing throttle for command vectors: the first value goes out
 * at once, later ones at most every `intervalMs`, and the newest always wins.
 */
export class CommandThrottle {
  private pending: FingerValues | null = null
  private lastSent = 0
  private timer: ReturnType<typeof setTimeout> | null = null

  constructor(
    private readonly send: (data: FingerValues) => void,
    private readonly intervalMs: number,
  ) {}

  push(data: FingerValues): void {
    this.pending = data
    const wait = this.intervalMs - (performance.now() - this.lastSent)
    if (wait <= 0) this.flush()
    else this.timer ??= setTimeout(this.flush, wait)
  }

  /** Drop anything not sent yet. */
  cancel(): void {
    if (this.timer !== null) clearTimeout(this.timer)
    this.timer = null
    this.pending = null
  }

  private readonly flush = (): void => {
    this.timer = null
    if (this.pending === null) return
    this.send(this.pending)
    this.pending = null
    this.lastSent = performance.now()
  }
}
