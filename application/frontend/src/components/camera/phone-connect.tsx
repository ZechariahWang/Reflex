"use client"

import { useState, type FormEvent } from "react"
import { motion } from "motion/react"

import { StatusDot, type Status } from "@/components/console/status-dot"
import { Button } from "@/components/ui/button"
import { connectPhone, type PhoneState } from "@/hooks/use-phone"
import type { PhoneStatus } from "@/lib/types"

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

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    await connectPhone(host)
    setBusy(false)
    setDraft(null)
    onDone?.()
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
            placeholder="192.168.1.23"
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
        </span>

        <span className="label-micro leading-relaxed tracking-normal normal-case">
          {error ?? (phone?.state === "error" ? phone.detail : null) ??
            "Record3D app › Wi-Fi streaming › start. Phone and this computer on the same network; the address is shown in the app."}
        </span>
      </form>
    </motion.div>
  )
}
