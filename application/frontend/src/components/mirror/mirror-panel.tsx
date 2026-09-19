"use client"

import { Panel, PanelNotice } from "@/components/console/panel"
import { MirrorViewport } from "@/components/mirror/mirror-viewport"
import { useMirrorStore } from "@/lib/mirror-store"

/**
 * Panel 02, always on the page next to the 3D hand, so the controller sees their own tracked
 * hand and the robot hand's answer together. The webcam and /ws/mirror exist only while the
 * Mirror switch is on: `MirrorViewport` owns both and is mounted for exactly that long. An
 * always-visible panel must not become an always-on camera that commands the hand.
 */
export function MirrorPanel() {
  const enabled = useMirrorStore((store) => store.enabled)
  if (enabled) return <MirrorViewport />
  return (
    <Panel
      index="02"
      title="Mirror"
      tag="/ws/mirror"
      status="offline"
      statusLabel="Off"
      keepStatusLabel
      footer={
        <>
          <span>webcam off</span>
          <span className="shrink-0">never recorded</span>
        </>
      }
    >
      <PanelNotice
        status="offline"
        label="Mirror off"
        detail="your hand in the webcam drives the fingers"
        hint="arm, then flip Mirror in the command block"
      />
    </Panel>
  )
}
