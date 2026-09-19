/**
 * Reads small regions of a streaming canvas. The stream canvas stays GPU-backed; the region
 * is copied into a tiny software canvas made for readback, which is the fast path.
 */
export class PixelSampler {
  private readonly context: CanvasRenderingContext2D | null

  constructor(
    private readonly width: number,
    private readonly height: number,
  ) {
    const canvas = document.createElement("canvas")
    canvas.width = width
    canvas.height = height
    this.context = canvas.getContext("2d", { willReadFrequently: true })
  }

  /** The source rectangle scaled into the sampler's size, as RGBA bytes; null if unreadable. */
  read(source: HTMLCanvasElement, x: number, y: number, width: number, height: number): Uint8ClampedArray | null {
    if (!this.context || source.width === 0 || source.height === 0) return null
    this.context.drawImage(source, x, y, width, height, 0, 0, this.width, this.height)
    return this.context.getImageData(0, 0, this.width, this.height).data
  }
}
