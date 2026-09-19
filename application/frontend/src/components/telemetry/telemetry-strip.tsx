"use client"

import { Panel } from "@/components/console/panel"
import type { Status } from "@/components/console/status-dot"
import { CommandBlock } from "@/components/telemetry/command-block"
import { FingerColumn, type Flow } from "@/components/telemetry/finger-column"
import { useHealth } from "@/hooks/use-health"
import { selectSnapshot, selectStatus, useSimStore } from "@/lib/sim-store"
import { FINGERS, TOPIC_NAMES } from "@/lib/types"

const PANEL_STATUS: Record<Flow, { status: Status; label: string }> = {
  live: { status: "live", label: "Live" },
  stale: { status: "waiting", label: "No ROS" },
  offline: { status: "offline", label: "Offline" },
}

function Legend() {
  return (
    <span className="label-micro hidden items-center gap-4 lg:flex" aria-hidden>
      <span className="flex items-center gap-1.5">
        <span className="h-px w-3 bg-ink" />
        Measured
      </span>
      <span className="flex items-center gap-1.5">
        <span className="w-3 border-t border-dashed border-ink-mute" />
        Command
      </span>
    </span>
  )
}

export function TelemetryStrip() {
  const socket = useSimStore(selectStatus)
  const snapshot = useSimStore(selectSnapshot)
  const { reachable } = useHealth()

  const flow: Flow = socket !== "open" || !snapshot ? "offline" : snapshot.ros_connected ? "live" : "stale"
  // Until the API is known to be down, a closed socket is still "connecting", not "offline".
  const connecting = flow === "offline" && reachable !== false
  const { status, label } = connecting ? { status: "waiting" as const, label: "Connecting" } : PANEL_STATUS[flow]

  return (
    <Panel
      index="04"
      title="Telemetry"
      tag={TOPIC_NAMES.hand_state}
      status={status}
      statusLabel={label}
      actions={<Legend />}
      contentClassName="grid console:grid-cols-[minmax(0,1fr)_23rem] console:grid-rows-[minmax(0,1fr)]"
    >
      <div className="grid min-h-0 divide-y sm:grid-cols-5 sm:divide-x sm:divide-y-0">
        {FINGERS.map((finger, i) => (
          <FingerColumn
            key={finger}
            finger={i}
            flow={flow}
            state={snapshot?.state[i] ?? null}
            command={snapshot?.command?.[i] ?? null}
            radians={snapshot?.joints[`${finger}_joint`] ?? null}
          />
        ))}
      </div>
      <div className="min-h-0 border-t console:border-t-0 console:border-l">
        <CommandBlock />
      </div>
    </Panel>
  )
}
