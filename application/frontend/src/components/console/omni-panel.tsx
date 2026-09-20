"use client"

import { useEffect, useRef, useState } from "react"
import { Mic, Play, Send, Square, Volume2, VolumeX, RotateCcw } from "lucide-react"
import { Panel } from "@/components/console/panel"
import { BACKEND_URL } from "@/lib/config"
import { recordingToWav } from "@/lib/omni-audio"
import { selectMovement, useSimStore } from "@/lib/sim-store"

type Reply = {
  heard: string; scene: string; reply: string; movement: string | null
  proposal_id: string | null; expires_in: number; elapsed_ms: number
  model: string; mock: boolean; camera: string; audio_received: boolean
}
type Turn = Reply & { id: number; expiresAt: number; executed?: boolean }
const button = "inline-flex size-9 shrink-0 items-center justify-center border bg-white text-ink hover:bg-black/5 disabled:opacity-35"

async function api(path: string, body?: object, signal?: AbortSignal) {
  const response = await fetch(`${BACKEND_URL}/api/omni/${path}`, {
    method: body ? "POST" : "GET", headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined, signal,
  })
  const result = await response.json()
  if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Request failed.")
  return result
}

export function OmniPanel() {
  const [config, setConfig] = useState<{ configured: boolean; model: string; mock: boolean } | null>(null)
  const [camera, setCamera] = useState("realsense")
  const [text, setText] = useState("")
  const [turns, setTurns] = useState<Turn[]>([])
  const [phase, setPhase] = useState("idle")
  const [error, setError] = useState("")
  const [muted, setMuted] = useState(false)
  const [now, setNow] = useState(0)
  const recorder = useRef<MediaRecorder | null>(null)
  const recordingTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const controller = useRef<AbortController | null>(null)
  const generation = useRef(0)
  const locked = useRef(false)
  const bottom = useRef<HTMLDivElement>(null)
  const movement = useSimStore(selectMovement)

  useEffect(() => {
    const lifecycle = generation
    const poll = () => api("status").then(setConfig).catch(() => setConfig(null))
    void poll()
    const timer = setInterval(() => { setNow(Date.now()); void poll() }, 3000)
    return () => {
      clearInterval(timer)
      lifecycle.current++
      controller.current?.abort()
      if (recordingTimer.current) clearTimeout(recordingTimer.current)
      const current = recorder.current
      if (current) { current.onstop = null; if (current.state !== "inactive") current.stop(); current.stream.getTracks().forEach(t => t.stop()) }
      window.speechSynthesis?.cancel()
    }
  }, [])
  useEffect(() => { bottom.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }) }, [turns, phase])

  async function submit(audio?: string, token = generation.current) {
    setPhase("thinking"); setError("")
    setTurns(previous => previous.map(turn => ({ ...turn, proposal_id: null })))
    controller.current = new AbortController()
    const timeout = setTimeout(() => controller.current?.abort(), 65000)
    try {
      const reply: Reply = await api("turn", { text, audio, camera }, controller.current.signal)
      if (token !== generation.current) return
      setTurns(previous => [...previous.slice(-7), { ...reply, id: Date.now(), expiresAt: Date.now() + reply.expires_in * 1000 }])
      setNow(Date.now()); setText("")
      if (!muted && window.speechSynthesis) {
        window.speechSynthesis.cancel()
        window.speechSynthesis.speak(new SpeechSynthesisUtterance(reply.reply))
      }
    } catch (e) {
      if (token === generation.current) setError(e instanceof Error ? e.message : "Qwen request failed.")
    } finally {
      clearTimeout(timeout)
      if (token === generation.current) { setPhase("idle"); locked.current = false }
    }
  }

  async function record() {
    if (recorder.current?.state === "recording") { recorder.current.stop(); return }
    if (locked.current) return
    locked.current = true
    const token = ++generation.current
    setError(""); setPhase("microphone")
    window.speechSynthesis?.cancel()
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      if (token !== generation.current) { stream.getTracks().forEach(t => t.stop()); return }
      let current: MediaRecorder
      try { current = new MediaRecorder(stream) }
      catch (e) { stream.getTracks().forEach(t => t.stop()); throw e }
      recorder.current = current
      const chunks: Blob[] = []
      current.ondataavailable = event => { if (event.data.size) chunks.push(event.data) }
      current.onstop = async () => {
        stream.getTracks().forEach(t => t.stop())
        if (recordingTimer.current) clearTimeout(recordingTimer.current)
        recorder.current = null
        if (token !== generation.current) return
        setPhase("encoding")
        try {
          const audio = await recordingToWav(new Blob(chunks, { type: current.mimeType }))
          if (token === generation.current) await submit(audio, token)
        } catch (e) {
          if (token === generation.current) { setError(e instanceof Error ? e.message : "Audio capture failed."); setPhase("idle"); locked.current = false }
        }
      }
      current.start(); setPhase("listening")
      recordingTimer.current = setTimeout(() => { if (current.state === "recording") current.stop() }, 15000)
    } catch (e) {
      if (token === generation.current) { setError(e instanceof Error ? e.message : "Microphone unavailable."); setPhase("idle"); locked.current = false }
    }
  }

  async function stop(reset = false) {
    generation.current++
    controller.current?.abort()
    if (recordingTimer.current) clearTimeout(recordingTimer.current)
    if (recorder.current?.state === "recording") recorder.current.stop()
    window.speechSynthesis?.cancel()
    locked.current = true; setPhase("stopping"); setError("")
    setTurns(previous => reset ? [] : previous.map(turn => ({ ...turn, proposal_id: null })))
    try { await api(reset ? "reset" : "stop", {}) }
    catch (e) { setError(e instanceof Error ? e.message : "Stop failed.") }
    finally { locked.current = false; setPhase("idle") }
  }

  async function execute(turn: Turn) {
    if (locked.current) return
    locked.current = true; setPhase("executing"); setError("")
    try {
      await api("execute", { proposal_id: turn.proposal_id })
      setTurns(previous => previous.map(item => item.id === turn.id ? { ...item, executed: true, proposal_id: null } : item))
    } catch (e) { setError(e instanceof Error ? e.message : "Execution failed.") }
    finally { locked.current = false; setPhase("idle") }
  }

  return <Panel index="07" title="OMNI / Piano" status={config?.configured ? "live" : "waiting"}
    statusLabel={phase === "idle" ? (config?.configured ? "Ready" : "Setup") : phase} keepStatusLabel
    contentClassName="flex flex-col" footer={<><span className="truncate">{config?.model ?? "Qwen"}</span><span>{config?.mock ? "SIMULATED" : "LIVE ROS"}</span></>}>
    <div className="flex flex-wrap items-center gap-2 border-b p-2">
      <select aria-label="Qwen camera" value={camera} disabled={phase !== "idle"} onChange={e => setCamera(e.target.value)} className="min-w-0 flex-1 border bg-white p-2 text-xs">
        <option value="realsense">Wrist camera</option><option value="iphone">Head camera</option>
      </select>
      <button className={button} title={muted ? "Enable speech" : "Mute speech"} aria-label={muted ? "Enable speech" : "Mute speech"} onClick={() => { setMuted(!muted); window.speechSynthesis?.cancel() }}>{muted ? <VolumeX size={15} /> : <Volume2 size={15} />}</button>
      <button className={button} title="New conversation" aria-label="New conversation" disabled={phase === "stopping"} onClick={() => void stop(true)}><RotateCcw size={15} /></button>
    </div>
    <div role="log" aria-label="Qwen conversation" aria-live="polite" className="min-h-48 flex-1 space-y-5 overflow-y-auto p-3 console:min-h-0">
      {!turns.length && <div className="space-y-3 py-4"><p className="text-lg font-medium">Your hand. Your music.</p><p className="text-sm text-ink-mute">{config?.configured ? "What shall we play?" : "Qwen connection not configured."}</p></div>}
      {turns.map(turn => <article key={turn.id} className="space-y-2 border-b pb-4 text-sm wrap-anywhere">
        <p className="font-medium">{turn.heard || "Scene request"}</p>
        <p className="text-xs text-ink-mute">{turn.camera === "realsense" ? "Wrist" : "Head"} / {turn.scene}</p>
        <p>{turn.reply}</p>
        <div className="flex flex-wrap gap-2 text-[10px] text-ink-mute"><span>{turn.audio_received ? "AUDIO + VISION + LANGUAGE" : "VISION + LANGUAGE"}</span><span>{(turn.elapsed_ms / 1000).toFixed(1)} s</span></div>
        {turn.movement && <div className="flex flex-wrap items-center justify-between gap-2"><span className="text-xs">{turn.movement.replaceAll("_", " ")}</span><button className="inline-flex items-center gap-2 border px-3 py-2 text-xs disabled:opacity-40" disabled={!turn.proposal_id || now >= turn.expiresAt || phase !== "idle" || !!movement} onClick={() => void execute(turn)}><Play size={13} />{turn.executed ? "Started" : now >= turn.expiresAt ? "Expired" : !turn.proposal_id ? "Cancelled" : "Execute"}</button></div>}
      </article>)}
      {phase !== "idle" && <p className="text-xs text-ink-mute" role="status">{phase === "listening" ? "Listening..." : phase === "thinking" ? "Looking and listening..." : `${phase}...`}</p>}
      <div ref={bottom} />
    </div>
    {movement && <div className="border-t p-3 text-xs"><div className="mb-2 flex justify-between gap-2"><span>{movement.title}</span><span>{movement.step}/{movement.steps}</span></div><progress aria-label="Movement progress" className="h-1 w-full accent-orange-600" max={movement.steps} value={movement.step} /></div>}
    {error && <p role="alert" className="border-t p-3 text-xs text-red-700 wrap-anywhere">{error}</p>}
    <form className="space-y-2 border-t p-2" onSubmit={event => { event.preventDefault(); if (!text.trim() || locked.current) return; locked.current = true; void submit() }}>
      <textarea aria-label="Request for Qwen" placeholder="Play Hot Cross Buns" rows={2} maxLength={2000} value={text} onChange={event => setText(event.target.value)} disabled={phase !== "idle"} className="w-full resize-none border bg-white p-2 text-sm" />
      <div className="flex items-center gap-2">
        <button type="button" title={phase === "listening" ? "Send recording" : "Record voice or melody"} aria-label={phase === "listening" ? "Send recording" : "Record voice or melody"} aria-pressed={phase === "listening"} className={`${button} ${phase === "listening" ? "text-red-600" : ""}`} disabled={!config?.configured || (phase !== "idle" && phase !== "listening")} onClick={() => void record()}>{phase === "listening" ? <Square size={15} /> : <Mic size={15} />}</button>
        <button type="submit" title="Send request" aria-label="Send request" className={button} disabled={!config?.configured || !text.trim() || phase !== "idle"}><Send size={15} /></button>
        <button type="button" className="ml-auto inline-flex h-9 items-center gap-2 border border-red-700 px-3 text-xs text-red-700 disabled:opacity-40" disabled={phase === "stopping"} onClick={() => void stop()}><Square size={13} />Stop</button>
      </div>
    </form>
  </Panel>
}
