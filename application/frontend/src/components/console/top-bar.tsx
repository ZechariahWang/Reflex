"use client"

import { Fragment, useEffect, useState } from "react"
import { AnimatePresence, motion, type Variants } from "motion/react"

import { StatusDot, type Status } from "@/components/console/status-dot"
import { TweenedNumber } from "@/components/console/tweened-number"
import { useHealth } from "@/hooks/use-health"
import { BACKEND_URL } from "@/lib/config"
import { selectSnapshot, selectStatus, useSimStore } from "@/lib/sim-store"
import type { TopicKey } from "@/lib/types"
import { cn } from "@/lib/utils"

const EASE = [0.22, 1, 0.36, 1] as const

const bar: Variants = {
  hidden: {},
  shown: { transition: { staggerChildren: 0.08 } },
}

const zone: Variants = {
  hidden: { opacity: 0, y: -6 },
  shown: { opacity: 1, y: 0, transition: { duration: 0.6, ease: EASE } },
}

/** Short tags for the bar; the panels carry the full topic names. */
const RATE_TOPICS: readonly { key: TopicKey; tag: string; wide?: boolean }[] = [
  { key: "joint_states", tag: "/joint_states" },
  { key: "hand_state", tag: "/hand/state" },
  { key: "hand_command", tag: "/hand/command" },
  { key: "color", tag: "/camera/color", wide: true },
  { key: "depth", tag: "/camera/depth", wide: true },
  { key: "iphone", tag: "/head_camera", wide: true },
]

const stripScheme = (url: string) => url.replace(/^\w+:\/\//, "")

interface Link {
  /** Browser <-> backend: the /ws/state socket, or a health poll that answered. */
  api: boolean
  /** Backend <-> rosbridge. */
  bridge: boolean
  /** rosbridge <-> ROS nodes: hand topics are actually arriving. */
  ros: boolean
  mock: boolean
  mode: { label: string; status: Status; source: string }
}

function useLink(): Link {
  const socket = useSimStore(selectStatus)
  const snapshot = useSimStore(selectSnapshot)
  const { health, reachable } = useHealth()

  const open = socket === "open"
  const api = open || reachable === true
  const mock = api && (health?.mock ?? false)
  const bridge = open ? (snapshot?.ros_connected ?? false) : api && (health?.ros_connected ?? false)
  const ros = bridge && open && snapshot !== null && (snapshot.rates.joint_states > 0 || snapshot.rates.hand_state > 0)
  const rosbridge = stripScheme(health?.rosbridge_url ?? "rosbridge")

  let mode: Link["mode"]
  if (!api) {
    mode =
      reachable === null
        ? { label: "Connecting", status: "waiting", source: stripScheme(BACKEND_URL) }
        : { label: "Offline", status: "offline", source: "api unreachable" }
  } else if (mock) {
    mode = { label: "Mock", status: "live", source: "synthetic source" }
  } else if (bridge) {
    mode = { label: "Live", status: "live", source: rosbridge }
  } else {
    mode = { label: "Offline", status: "waiting", source: "no rosbridge" }
  }

  return { api, bridge, ros, mock, mode }
}

function Wordmark() {
  return (
    <div className="flex items-center gap-3">
      <span className="font-mono text-base leading-none tracking-tight text-ink" aria-label="HTN">
        <span className="text-ink-mute">[/</span>
        HTN
        <span className="text-ink-mute">]</span>
      </span>
      <span aria-hidden className="h-3 w-px bg-hairline" />
      <span className="text-[15px] leading-none font-medium tracking-tight">Hand Console</span>
    </div>
  )
}

function Mode({ mode }: { mode: Link["mode"] }) {
  return (
    <div className="flex items-center gap-2.5" role="status">
      <span className="label-micro hidden sm:inline">Mode</span>
      <StatusDot status={mode.status} />
      <AnimatePresence mode="wait" initial={false}>
        <motion.span
          key={`${mode.label}:${mode.source}`}
          initial={{ opacity: 0, y: 3 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -3 }}
          transition={{ duration: 0.2, ease: EASE }}
          className="flex items-baseline gap-2.5"
        >
          <span className={cn("label-micro", mode.status === "live" ? "text-ink" : "text-ink-soft")}>{mode.label}</span>
          <span className="label-micro hidden tracking-normal normal-case sm:inline">{mode.source}</span>
        </motion.span>
      </AnimatePresence>
    </div>
  )
}

/** ROS - BRIDGE - API - UI: each hop inks in, in the direction the data flows, once it carries data. */
function Chain({ link }: { link: Link }) {
  const hops = [link.ros, link.bridge, link.api]
  const nodes = [link.mock ? "Mock" : "ROS", "Bridge", "API", "UI"]

  return (
    <div className="hidden items-center gap-2 md:flex" aria-label="Connection chain">
      {nodes.map((node, i) => {
        const lit = i === nodes.length - 1 || hops[i] || (i > 0 && hops[i - 1])
        return (
          <Fragment key={node}>
            <span className="flex items-center gap-1.5">
              <span
                aria-hidden
                className={cn(
                  "size-[5px] border transition-colors duration-500",
                  lit ? "border-ink bg-ink" : "border-ink-mute bg-transparent",
                )}
              />
              <span className={cn("label-micro transition-colors duration-500", lit && "text-ink")}>{node}</span>
            </span>
            {i < hops.length && (
              <span aria-hidden className="relative h-px w-4 bg-hairline">
                <motion.span
                  className="absolute inset-0 origin-left bg-ink"
                  initial={false}
                  animate={{ scaleX: hops[i] ? 1 : 0 }}
                  transition={{ duration: 0.5, ease: EASE, delay: hops[i] ? i * 0.12 : 0 }}
                />
              </span>
            )}
          </Fragment>
        )
      })}
    </div>
  )
}

function SessionClock() {
  const [seconds, setSeconds] = useState(0)

  useEffect(() => {
    const started = performance.now()
    const timer = setInterval(() => setSeconds(Math.floor((performance.now() - started) / 1000)), 1000)
    return () => clearInterval(timer)
  }, [])

  const part = (n: number) => String(n).padStart(2, "0")
  return (
    <span className="label-micro flex items-baseline gap-2" aria-label="Session time">
      T+
      <span className="num text-ink">
        {part(Math.floor(seconds / 3600))}:{part(Math.floor(seconds / 60) % 60)}:{part(seconds % 60)}
      </span>
    </span>
  )
}

function Rates() {
  const open = useSimStore(selectStatus) === "open"
  const rates = useSimStore(selectSnapshot)?.rates

  return (
    <div className="flex items-baseline justify-center gap-6">
      {RATE_TOPICS.map(({ key, tag, wide }) => (
        <span
          key={key}
          className={cn("label-micro items-baseline gap-1.5 tracking-normal normal-case", wide ? "hidden 2xl:flex" : "flex")}
        >
          {tag}
          <TweenedNumber
            value={open && rates ? Math.round(rates[key]) : null}
            duration={0.4}
            delay={0.4}
            className="min-w-[2ch] text-right text-ink"
          />
          Hz
        </span>
      ))}
    </div>
  )
}

function Divider({ className }: { className: string }) {
  return <span aria-hidden className={cn("hidden h-3 w-px bg-hairline", className)} />
}

export function TopBar() {
  const link = useLink()

  return (
    <motion.header
      variants={bar}
      initial="hidden"
      animate="shown"
      className="flex min-h-10 flex-wrap items-center justify-between gap-x-6 gap-y-2 border-b border-hairline px-1 pb-2 xl:grid xl:grid-cols-[auto_minmax(0,1fr)_auto]"
    >
      <motion.div variants={zone} className="flex items-center gap-6">
        <Wordmark />
        <Mode mode={link.mode} />
      </motion.div>
      <motion.div variants={zone} className="hidden xl:block">
        <Rates />
      </motion.div>
      <motion.div variants={zone} className="flex items-center gap-4">
        <Chain link={link} />
        <Divider className="md:block" />
        <SessionClock />
      </motion.div>
    </motion.header>
  )
}
