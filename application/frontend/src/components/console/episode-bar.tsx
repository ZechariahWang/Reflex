"use client"

import { useCallback, useEffect, useState } from "react"

import { StatusDot } from "@/components/console/status-dot"
import { Button } from "@/components/ui/button"
import { API } from "@/lib/config"
import { selectMovement, selectMovementName, selectSession, selectSessionMode, useSimStore } from "@/lib/sim-store"
import type { EpisodeDataset, Movement } from "@/lib/types"

const FIELD =
  "h-6 min-w-0 rounded-[2px] border border-border bg-surface px-1.5 font-mono text-[11px] text-ink outline-none focus:border-ink-mute disabled:opacity-50"
const ACTION = "label-micro h-6 rounded-[2px] bg-surface"

async function call(path: string, body?: object, base: string = API.episodes): Promise<{ ok: boolean; data: unknown }> {
  try {
    const response = await fetch(`${base}${path}`, {
      method: body ? "POST" : "GET",
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    })
    return { ok: response.ok, data: await response.json() }
  } catch {
    return { ok: false, data: { detail: "backend unreachable" } }
  }
}

/**
 * Record what the console sees as episodes (state, the last command as the action, both cameras)
 * and play one back: the hand is commanded again and the camera panels show the recording.
 * The backend does both (`app/episodes.py`); its progress arrives as `session` in /ws/state.
 */
export function EpisodeBar() {
  const mode = useSimStore(selectSessionMode)
  const [datasets, setDatasets] = useState<EpisodeDataset[]>([])
  const [name, setName] = useState("exo_grasp")
  // The constant instruction of the policy (policy/README.md): every dataset and the inference use this string
  const [task, setTask] = useState("grasp and put down objects, make a peace sign at a person")
  const [episode, setEpisode] = useState(0)
  const [what, setWhat] = useState<"action" | "state">("action")
  const [error, setError] = useState<string | null>(null)

  const take = useCallback((result: { ok: boolean; data: unknown }) => {
    const data = result.data as { datasets?: EpisodeDataset[]; detail?: string }
    if (data.datasets) setDatasets(data.datasets)
    setError(result.ok ? null : (data.detail ?? "request failed"))
  }, [])

  // On load, and whenever a recording or a replay ends: the list may have a new episode.
  useEffect(() => {
    if (mode === "idle") void call("").then(take)
  }, [mode, take])

  const selected = datasets.find((dataset) => dataset.name === name)
  const count = selected?.episodes.length ?? 0
  const shown = Math.min(episode, Math.max(0, count - 1))
  const idle = mode === "idle"

  return (
    <section
      aria-label="Episodes"
      className="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-[3px] border border-border bg-surface/60 px-2.5 py-1.5"
    >
      <span className="label-micro text-ink">Episodes</span>
      <input
        aria-label="Dataset name"
        list="episode-datasets"
        value={name}
        disabled={!idle}
        onChange={(event) => setName(event.target.value)}
        className={`${FIELD} w-32`}
      />
      <datalist id="episode-datasets">
        {datasets.map((dataset) => (
          <option key={dataset.name} value={dataset.name} />
        ))}
      </datalist>
      <input
        aria-label="Task"
        value={selected?.task || task}
        disabled={!idle || Boolean(selected)}
        onChange={(event) => setTask(event.target.value)}
        className={`${FIELD} w-44`}
      />

      {mode === "recording" ? (
        <>
          <Button variant="outline" size="xs" className={ACTION} onClick={() => void call("/stop", { keep: true }).then(take)}>
            Save
          </Button>
          <Button variant="outline" size="xs" className={ACTION} onClick={() => void call("/stop", { keep: false }).then(take)}>
            Discard
          </Button>
        </>
      ) : (
        <Button
          variant="outline"
          size="xs"
          className={ACTION}
          disabled={!idle || name === ""}
          onClick={() => void call("/record", { dataset: name, task }).then(take)}
        >
          Record
        </Button>
      )}

      <span className="h-4 w-px bg-border" aria-hidden />

      <select
        aria-label="Episode"
        value={shown}
        disabled={!idle || count === 0}
        onChange={(event) => setEpisode(Number(event.target.value))}
        className={`${FIELD} w-40`}
      >
        {count === 0 && <option>no episodes</option>}
        {selected?.episodes.map((frames, index) => (
          <option key={index} value={index}>
            episode {index} · {(frames / selected.fps).toFixed(1)} s
          </option>
        ))}
      </select>
      <select
        aria-label="What to replay"
        value={what}
        disabled={!idle}
        onChange={(event) => setWhat(event.target.value as "action" | "state")}
        className={`${FIELD} w-24`}
      >
        <option value="action">commands</option>
        <option value="state">measured</option>
      </select>
      {mode === "replaying" ? (
        <Button variant="outline" size="xs" className={ACTION} onClick={() => void call("/stop", {}).then(take)}>
          Stop
        </Button>
      ) : (
        <Button
          variant="outline"
          size="xs"
          className={ACTION}
          disabled={!idle || count === 0}
          onClick={() => void call("/replay", { dataset: name, episode: shown, what, speed: 1 }).then(take)}
        >
          Replay
        </Button>
      )}

      <span className="h-4 w-px bg-border" aria-hidden />

      <MovementPlayer replaying={mode === "replaying"} onError={setError} />

      <Progress />
      {error && <span className="label-micro tracking-normal text-signal normal-case">{error}</span>}
    </section>
  )
}

/**
 * Pre-written movements: the scripts of the repo's `movements/` folder (hot cross buns on three
 * keys, ...). One can play while an episode is recorded - that records a demonstration.
 */
function MovementPlayer({ replaying, onError }: { replaying: boolean; onError: (error: string | null) => void }) {
  const playing = useSimStore(selectMovementName)
  const [movements, setMovements] = useState<Movement[]>([])
  const [name, setName] = useState("")

  useEffect(() => {
    void call("", undefined, API.movements).then(({ ok, data }) => {
      if (ok && Array.isArray(data)) setMovements(data as Movement[])
    })
  }, [])

  const chosen = movements.find((movement) => movement.name === name) ?? movements[0]
  const report = ({ ok, data }: { ok: boolean; data: unknown }) =>
    onError(ok ? null : ((data as { detail?: string }).detail ?? "request failed"))

  return (
    <>
      <select
        aria-label="Movement"
        value={chosen?.name ?? ""}
        disabled={playing !== null || movements.length === 0}
        onChange={(event) => setName(event.target.value)}
        title={chosen?.error ?? chosen?.description}
        className={`${FIELD} w-44`}
      >
        {movements.length === 0 && <option value="">no movements</option>}
        {movements.map((movement) => (
          <option key={movement.name} value={movement.name} disabled={movement.error !== null}>
            {movement.title} · {movement.error ? "broken" : `${movement.seconds.toFixed(0)} s`}
          </option>
        ))}
      </select>
      {playing !== null ? (
        <Button variant="outline" size="xs" className={ACTION} onClick={() => void call("/stop", {}, API.movements).then(report)}>
          Stop
        </Button>
      ) : (
        <Button
          variant="outline"
          size="xs"
          className={ACTION}
          disabled={replaying || !chosen || chosen.error !== null}
          onClick={() => void call("/play", { name: chosen?.name }, API.movements).then(report)}
        >
          Play
        </Button>
      )}
    </>
  )
}

/** Its own component: it renders at the snapshot rate, the bar around it does not. */
function Progress() {
  const session = useSimStore(selectSession)
  const movement = useSimStore(selectMovement)
  if (session.mode === "idle" && movement)
    return (
      <span className="flex items-center gap-2">
        <StatusDot status="live" />
        <span className="label-micro tracking-normal text-ink normal-case">
          playing {movement.title} · step {movement.step} of {movement.steps}
          {movement.waiting && " · waiting for the hand"}
          {movement.not_arrived > 0 && ` · ${movement.not_arrived} not reached`}
        </span>
      </span>
    )
  if (session.mode === "idle") return <span className="label-micro tracking-normal normal-case">idle</span>
  const seconds = (session.frame / 30).toFixed(1)
  return (
    <span className="flex items-center gap-2">
      <StatusDot status={session.mode === "recording" ? "live" : "waiting"} />
      <span className="label-micro tracking-normal text-ink normal-case">
        {session.mode} {session.dataset} / episode {session.episode} · {seconds} s
        {session.frames !== null && ` of ${(session.frames / 30).toFixed(1)} s`}
        {movement && ` · playing ${movement.title}`}
      </span>
    </span>
  )
}
