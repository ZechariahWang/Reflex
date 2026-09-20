/** Decode the browser's recording and send real mono PCM audio to Qwen. */
export async function recordingToWav(blob: Blob): Promise<string> {
  const context = new AudioContext()
  try {
    const decoded = await context.decodeAudioData(await blob.arrayBuffer())
    const renderer = new OfflineAudioContext(1, Math.ceil(decoded.duration * 16000), 16000)
    const source = renderer.createBufferSource()
    source.buffer = decoded
    source.connect(renderer.destination)
    source.start()
    const rendered = await renderer.startRendering()
    const samples = rendered.getChannelData(0)
    const bytes = new Uint8Array(44 + samples.length * 2)
    const view = new DataView(bytes.buffer)
    const write = (offset: number, value: string) => {
      for (let i = 0; i < value.length; i++) bytes[offset + i] = value.charCodeAt(i)
    }
    write(0, "RIFF"); view.setUint32(4, bytes.length - 8, true)
    write(8, "WAVEfmt "); view.setUint32(16, 16, true)
    view.setUint16(20, 1, true); view.setUint16(22, 1, true)
    view.setUint32(24, 16000, true); view.setUint32(28, 32000, true)
    view.setUint16(32, 2, true); view.setUint16(34, 16, true)
    write(36, "data"); view.setUint32(40, samples.length * 2, true)
    samples.forEach((sample, i) => {
      const value = Math.max(-1, Math.min(1, sample))
      view.setInt16(44 + i * 2, value * (value < 0 ? 32768 : 32767), true)
    })
    let binary = ""
    for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192))
    return btoa(binary)
  } finally {
    await context.close()
  }
}
