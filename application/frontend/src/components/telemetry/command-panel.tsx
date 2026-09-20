"use client"

import { Panel } from "@/components/console/panel"
import type { Status } from "@/components/console/status-dot"
import { CommandBlock } from "@/components/telemetry/command-block"
import { useHealth } from "@/hooks/use-health"
import { selectSnapshot, selectStatus, useSimStore } from "@/lib/sim-store"
import { TOPIC_NAMES } from "@/lib/types"

type Flow = "live" | "stale" | "offline"

const PANEL_STATUS: Record<Flow, { status: Status; label: string }> = {
  live: { status: "live", label: "Live" },
  stale: { status: "waiting", label: "No ROS" },
  offline: { status: "offline", label: "Offline" },
}

/** Panel 05: the command block alone (sliders, Arm / Backdrive / Mirror, presets) under the 3D hand. */
export function CommandPanel() {
  const socket = useSimStore(selectStatus)
  const snapshot = useSimStore(selectSnapshot)
  const { reachable } = useHealth()

  const flow: Flow = socket !== "open" || !snapshot ? "offline" : snapshot.ros_connected ? "live" : "stale"
  // Until the API is known to be down, a closed socket is still "connecting", not "offline".
  const connecting = flow === "offline" && reachable !== false
  const { status, label } = connecting ? { status: "waiting" as const, label: "Connecting" } : PANEL_STATUS[flow]

  return (
    <Panel index="05" title="Command" tag={TOPIC_NAMES.hand_command} status={status} statusLabel={label}>
      <CommandBlock />
    </Panel>
  )
}
