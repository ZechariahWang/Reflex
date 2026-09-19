"use client"

import { Fragment, type ReactNode } from "react"
import { motion, type Variants } from "motion/react"

import { StatusDot, type Status } from "@/components/console/status-dot"
import { cn } from "@/lib/utils"

const EASE = [0.22, 1, 0.36, 1] as const
const STAGGER_S = 0.07

const frame: Variants = {
  hidden: { opacity: 0, y: 10 },
  shown: (delay: number) => ({
    opacity: 1,
    y: 0,
    transition: { duration: 0.7, ease: EASE, delay, delayChildren: delay + 0.35 },
  }),
}

const tick: Variants = {
  hidden: { opacity: 0, scale: 0.4 },
  shown: { opacity: 1, scale: 1, transition: { duration: 0.5, ease: EASE } },
}

const CORNERS = [
  "-top-px -left-px origin-top-left border-t border-l",
  "-top-px -right-px origin-top-right border-t border-r",
  "-bottom-px -left-px origin-bottom-left border-b border-l",
  "-right-px -bottom-px origin-bottom-right border-r border-b",
] as const

const STATUS_LABEL: Record<Status, string> = {
  live: "Live",
  waiting: "Standby",
  offline: "Offline",
}

export interface PanelProps {
  /** Two-digit section number, e.g. "01". Also sets the entrance order. */
  index: string
  title: string
  /** Slash-prefixed source, usually the ROS topic, e.g. "/joint_states". */
  tag?: string
  status?: Status
  /** Replaces the default status wording ("Live" / "Standby" / "Offline"). */
  statusLabel?: string
  /** Controls placed in the header, left of the status. */
  actions?: ReactNode
  /** Optional bottom margin row for coordinates, units and readouts. */
  footer?: ReactNode
  children: ReactNode
  className?: string
  /** Applied to the content area, which is `relative` and clips its children. */
  contentClassName?: string
}

/** The framed viewport chrome shared by every section of the console. */
export function Panel({
  index,
  title,
  tag,
  status,
  statusLabel,
  actions,
  footer,
  children,
  className,
  contentClassName,
}: PanelProps) {
  const delay = (Number.parseInt(index, 10) || 0) * STAGGER_S

  return (
    <motion.section
      aria-label={title}
      variants={frame}
      custom={delay}
      initial="hidden"
      animate="shown"
      className={cn("hairline-frame relative flex h-full min-h-0 min-w-0 flex-col", className)}
    >
      {CORNERS.map((corner) => (
        <motion.span
          key={corner}
          aria-hidden
          variants={tick}
          className={cn("pointer-events-none absolute z-10 size-2 border-ink", corner)}
        />
      ))}

      <header className="flex h-9 shrink-0 items-center gap-3 border-b px-3">
        <span className="label-micro num">{index}</span>
        <span aria-hidden className="h-3 w-px shrink-0 bg-hairline" />
        <h2 className="label-micro shrink-0 text-ink">{title}</h2>
        {tag && <span className="label-micro min-w-0 truncate leading-4 tracking-normal normal-case">{tag}</span>}

        <div className="ml-auto flex shrink-0 items-center gap-3">
          {actions}
          {status && (
            <span className="flex items-center gap-2">
              <StatusDot status={status} />
              <span className={cn("label-micro", status === "live" && "text-ink")}>
                {statusLabel ?? STATUS_LABEL[status]}
              </span>
            </span>
          )}
        </div>
      </header>

      <div className={cn("relative min-h-0 flex-1 overflow-hidden", contentClassName)}>{children}</div>

      {footer && (
        <footer className="label-micro flex h-7 shrink-0 items-center justify-between gap-3 border-t px-3">
          {footer}
        </footer>
      )}
    </motion.section>
  )
}

export interface PanelNoticeProps {
  label: string
  /** What is missing, usually a topic; long names wrap inside the card. */
  detail?: string
  /** Why, or what happens next. */
  hint?: string
  status?: Status
}

/** The one empty / pending / no-signal card: centred over the dotted grid. */
export function PanelNotice({ label, detail, hint, status }: PanelNoticeProps) {
  return (
    <div className="bg-dot-grid absolute inset-0 grid place-items-center p-4">
      <div className="flex max-w-[min(22rem,100%)] flex-col items-center gap-2 border border-hairline bg-surface px-5 py-3.5 text-center">
        <span className="flex items-center gap-2">
          {status && <StatusDot status={status} />}
          <span className="label-micro text-ink">{label}</span>
        </span>
        {detail && (
          <span className="label-micro leading-[1.5] wrap-anywhere tracking-normal normal-case">
            {/* Topic names break after a slash before they break anywhere else. */}
            {detail.split("/").map((segment, i) => (
              <Fragment key={i}>
                {i > 0 && "/"}
                {i > 0 && <wbr />}
                {segment}
              </Fragment>
            ))}
          </span>
        )}
        {hint && <span className="label-micro leading-[1.5] tracking-normal normal-case text-ink-mute/80">{hint}</span>}
      </div>
    </div>
  )
}
