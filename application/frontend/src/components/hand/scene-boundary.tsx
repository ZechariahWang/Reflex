"use client"

import { Component, type ReactNode } from "react"

interface SceneBoundaryProps {
  /** The panel takes over from here: it unmounts the scene and shows its own notice. */
  onError: () => void
  children: ReactNode
}

/**
 * Contains a throw from the three.js scene (URDF parsing, a lost WebGL context) to the
 * hand panel, so the cameras, the telemetry and the ARM switch keep running.
 */
export class SceneBoundary extends Component<SceneBoundaryProps, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true }
  }

  componentDidCatch(error: Error): void {
    console.error("hand scene failed:", error)
    this.props.onError()
  }

  render(): ReactNode {
    return this.state.failed ? null : this.props.children
  }
}
