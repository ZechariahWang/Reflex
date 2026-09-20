"use client"

import { CameraViewport } from "@/components/camera/camera-viewport"
import { HandViewport } from "@/components/hand/hand-viewport"
import { MirrorViewport } from "@/components/mirror/mirror-viewport"
import { CommandPanel } from "@/components/telemetry/command-panel"
import { OmniPanel } from "@/components/console/omni-panel"
import { useMirrorStore } from "@/lib/mirror-store"
import { cn } from "@/lib/utils"

/**
 * The stage: 3D hand with the command block under it / RealSense over iPhone / mirror. The hand
 * is the page's centrepiece and takes the width the mirror leaves. The mirror column (the controller's
 * webcam) is on the very right and exists only while the Mirror switch is on: `MirrorViewport`
 * owns the webcam and /ws/mirror and is mounted for exactly that long. With Mirror off the hand
 * takes the room.
 */
export function ConsoleStage() {
  const mirror = useMirrorStore((store) => store.enabled)
  return (
    <div
      className={cn(
        "grid min-h-0 grid-cols-[minmax(0,1fr)] gap-3",
        mirror
          ? "console:grid-cols-[minmax(0,40fr)_minmax(0,20fr)_minmax(0,20fr)_minmax(0,20fr)]"
          : "console:grid-cols-[minmax(0,50fr)_minmax(0,25fr)_minmax(0,25fr)]",
      )}
    >
      <div className="grid min-h-0 min-w-0 grid-cols-[minmax(0,1fr)] grid-rows-[minmax(0,1fr)_auto] gap-3">
        <div className="h-[70vw] max-h-[75dvh] min-h-0 console:h-auto console:max-h-none">
          <HandViewport />
        </div>
        <div className="min-h-0">
          <CommandPanel />
        </div>
      </div>
      <div className="grid min-h-0 grid-cols-[minmax(0,1fr)] gap-3 sm:grid-cols-2 console:grid-cols-1 console:grid-rows-2">
        <div className="aspect-4/3 min-h-0 console:aspect-auto">
          <CameraViewport source="realsense" />
        </div>
        <div className="aspect-4/3 min-h-0 console:aspect-auto">
          <CameraViewport source="iphone" />
        </div>
      </div>
      <div className="h-[600px] min-h-0 console:h-auto"><OmniPanel /></div>
      {mirror && (
        <div className="h-[90vw] max-h-[80dvh] min-h-0 console:h-auto console:max-h-none">
          <MirrorViewport />
        </div>
      )}
    </div>
  )
}
