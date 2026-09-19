export const VIEW_PRESETS = ["iso", "top", "side", "front"] as const

export type ViewPreset = (typeof VIEW_PRESETS)[number]

/** Camera direction per preset: azimuth from +Z toward +X, polar from +Y (three.js spherical). */
/** Side and front sit a few degrees above the horizon so the ground reads as a plane, not a line. */
const LEVEL = (84 * Math.PI) / 180

export const VIEW_ANGLES: Record<ViewPreset, { azimuth: number; polar: number }> = {
  iso: { azimuth: 0.72, polar: 1.08 },
  top: { azimuth: Math.PI / 2, polar: 0.02 },
  // The fingers point at +Z: from there it is the front, from +X the profile that shows the linkages work.
  side: { azimuth: Math.PI / 2, polar: LEVEL },
  front: { azimuth: 0, polar: LEVEL },
}

/** The idle orbit would walk the camera off an orthographic-style preset, so only these drift. */
export function allowsAutoOrbit(view: ViewPreset | null): boolean {
  return view === null || view === "iso"
}
