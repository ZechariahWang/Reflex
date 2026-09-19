export const VIEW_PRESETS = ["chase", "iso", "top", "side", "front"] as const

export type ViewPreset = (typeof VIEW_PRESETS)[number]

export interface ViewAngles {
  /** Camera direction: azimuth from +Z toward +X, polar from +Y (three.js spherical). */
  azimuth: number
  polar: number
  /** Camera distance as a multiple of the distance that fits the hand alone (default 1). */
  distance?: number
  /** Where the camera looks: metres ahead of the hand's centre, along the fingers (default 0). */
  ahead?: number
}

/** Side and front sit a few degrees above the horizon so the ground reads as a plane, not a line. */
const LEVEL = (84 * Math.PI) / 180

export const VIEW_ANGLES: Record<ViewPreset, ViewAngles> = {
  // Over the wrist, looking past the fingertips into the surroundings: the map view.
  chase: { azimuth: Math.PI, polar: 1.2, distance: 2.3, ahead: 0.3 },
  iso: { azimuth: 0.72, polar: 1.08 },
  top: { azimuth: Math.PI / 2, polar: 0.02 },
  // The fingers point at +Z: from there it is the front, from +X the profile that shows the linkages work.
  side: { azimuth: Math.PI / 2, polar: LEVEL },
  front: { azimuth: 0, polar: LEVEL },
}

/** The idle orbit would walk the camera off an orthographic-style preset (or off the map), so only these drift. */
export function allowsAutoOrbit(view: ViewPreset | null): boolean {
  return view === null || view === "iso"
}
