"use client"

import { useState, type FormEvent } from "react"
import { motion } from "motion/react"

import { StatusDot, type Status } from "@/components/console/status-dot"
import { Button } from "@/components/ui/button"
import { connectPhone, type PhoneState } from "@/hooks/use-phone"
import type { PhoneStatus } from "@/lib/types"

/** Address that selects the cable instead of the network. */
const USB = "usb"

const STATES: Record<PhoneStatus["state"], { status: Status; label: string }> = {
  off: { status: "offline", label: "Not connected" },
  connecting: { status: "waiting", label: "Connecting" },
  streaming: { status: "live", label: "Streaming" },
  error: { status: "offline", label: "Retrying" },
}

/**
 * Address card for the iPhone panel. The backend (not the browser) opens the
 * WebRTC session, so this only ever tells it where the phone is.
 */
export function PhoneConnect({ phone, error, onDone }: PhoneState & { onDone?: () => void }) {
  const [draft, setDraft] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const host = draft ?? phone?.host ?? ""
  const shown = STATES[phone?.state ?? "off"]

  const connect = async (address: string) => {
    setBusy(true)
    await connectPhone(address)
    setBusy(false)
    setDraft(null)
    onDone?.()
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    void connect(host)
  }

  return (
    <motion.div
      className="bg-dot-grid absolute inset-0 z-10 grid place-items-center bg-page/90 p-4"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.4 }}
    >
      <form
        onSubmit={submit}
        className="flex w-[min(21rem,100%)] flex-col gap-2.5 border border-hairline bg-surface px-5 py-4"
      >
        <span className="flex items-center justify-between gap-3">
          <span className="label-micro text-ink">iPhone · Record3D</span>
          <span className="flex items-center gap-1.5">
            <StatusDot status={shown.status} />
            <span className="label-micro">{shown.label}</span>
          </span>
        </span>

        <span className="flex gap-1.5">
          <input
            value={host}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="192.168.1.23 or usb"
            aria-label="iPhone address"
            spellCheck={false}
            autoComplete="off"
            className="num h-7 min-w-0 flex-1 border border-hairline bg-page px-2 text-[11px] text-ink outline-none placeholder:text-ink-mute/60 focus:border-ink"
          />
          <Button
            type="submit"
            size="xs"
            disabled={busy || phone === null}
            className="h-7 rounded-[2px] px-3 font-mono text-[10px] tracking-[0.14em] uppercase"
          >
            {host.trim() === "" && phone?.host ? "Disconnect" : "Connect"}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="xs"
            disabled={busy || phone === null}
            onClick={() => void connect(USB)}
            className="h-7 rounded-[2px] px-2.5 font-mono text-[10px] tracking-[0.14em] uppercase"
          >
            USB
          </Button>
        </span>

        <span className="label-micro leading-relaxed tracking-normal normal-case">
          {error ?? (phone?.state === "error" ? phone.detail : null) ??
            "Record3D › Settings › Live RGBD Video Streaming, then the red button. USB: cable, works on any network. Wi-Fi: type the address the app shows (not on eduroam, not via the phone's hotspot)."}
        </span>
      </form>
    </motion.div>
  )
}
