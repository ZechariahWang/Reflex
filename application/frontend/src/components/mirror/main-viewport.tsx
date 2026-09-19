"use client"

import { HandViewport } from "@/components/hand/hand-viewport"
import { MirrorViewport } from "@/components/mirror/mirror-viewport"
import { useMirrorStore } from "@/lib/mirror-store"

/** The large area of the console: the 3D hand, or the controller's panel while Mirror is on. */
export function MainViewport() {
  const mirror = useMirrorStore((store) => store.enabled)
  return mirror ? <MirrorViewport /> : <HandViewport />
}
