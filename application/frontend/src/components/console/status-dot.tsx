import { cn } from "@/lib/utils"

/**
 * live    - data flowing: the accent, with a slow pulse
 * waiting - connected or connecting, nothing to show yet: muted, blinking
 * offline - source unreachable: hollow ring
 */
export type Status = "live" | "waiting" | "offline"

export function StatusDot({ status, className }: { status: Status; className?: string }) {
  return (
    <span className={cn("relative inline-flex size-1.5 shrink-0", className)} aria-hidden>
      {status === "live" && (
        <span className="absolute inset-0 animate-pulse-live rounded-full bg-signal motion-reduce:hidden" />
      )}
      <span
        className={cn(
          "relative size-full rounded-full",
          status === "live" && "bg-signal",
          status === "waiting" && "animate-blink-wait bg-ink-mute motion-reduce:animate-none",
          status === "offline" && "border border-ink-mute",
        )}
      />
    </span>
  )
}
