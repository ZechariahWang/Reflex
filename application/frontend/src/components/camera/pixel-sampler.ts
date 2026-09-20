/**
 * Reads small regions of an image through a tiny software canvas made for readback. From a
 * GPU-backed source (the stream canvas) the copy waits for the GPU to finish everything it has
 * queued - fine for one pixel under the pointer, not on a timer: for that, `readFrame`.
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
  /** A whole frame (a JPEG as it arrived), decoded at the sampler's size off the main thread. */
  async readFrame(frame: Blob): Promise<Uint8ClampedArray | null> {
    if (!this.context) return null
    try {
      const bitmap = await createImageBitmap(frame, {
        resizeWidth: this.width,
        resizeHeight: this.height,
        resizeQuality: "low",
      })
      this.context.drawImage(bitmap, 0, 0)
      bitmap.close()
    } catch {
      return null // a truncated JPEG
    }
    return this.context.getImageData(0, 0, this.width, this.height).data
  }

  read(source: HTMLCanvasElement, x: number, y: number, width: number, height: number): Uint8ClampedArray | null {
    if (!this.context || source.width === 0 || source.height === 0) return null
    this.context.drawImage(source, x, y, width, height, 0, 0, this.width, this.height)
    return this.context.getImageData(0, 0, this.width, this.height).data
  }
}
