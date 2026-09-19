import * as motion from "motion/react-client"

import { CameraViewport } from "@/components/camera/camera-viewport"
import { TopBar } from "@/components/console/top-bar"
import { HandViewport } from "@/components/hand/hand-viewport"
import { TelemetryStrip } from "@/components/telemetry/telemetry-strip"
import { BACKEND_URL } from "@/lib/config"

import packageJson from "../../package.json"

const BUILD_TAG = `v${packageJson.version}-${process.env.NODE_ENV === "production" ? "prod" : "dev"}`

/** Lands last: top bar at 0, panels 01-04 at 70 ms steps, then this line. */
const FOOTER_DELAY_S = 0.75

/**
 * In the `console` variant (>= 1024 x 640) the page is exactly one screen:
 * top bar / hand 62 % + RealSense over iPhone / telemetry strip / footer line.
 * Below that it becomes a normal scrolling column.
 */
export default function ConsolePage() {
  return (
    <main className="mx-auto flex min-h-dvh max-w-[2400px] flex-col gap-3 p-3 console:grid console:h-dvh console:grid-rows-[auto_minmax(0,1fr)_clamp(9rem,21vh,13rem)_auto] console:overflow-hidden">
      <TopBar />

      <div className="grid min-h-0 grid-cols-[minmax(0,1fr)] gap-3 console:grid-cols-[minmax(0,62fr)_minmax(0,38fr)]">
        <div className="h-[70vw] max-h-[75dvh] min-h-0 console:h-auto console:max-h-none">
          <HandViewport />
        </div>
        <div className="grid min-h-0 grid-cols-[minmax(0,1fr)] gap-3 sm:grid-cols-2 console:grid-cols-1 console:grid-rows-2">
          <div className="aspect-4/3 min-h-0 console:aspect-auto">
            <CameraViewport source="realsense" />
          </div>
          <div className="aspect-4/3 min-h-0 console:aspect-auto">
            <CameraViewport source="iphone" />
          </div>
        </div>
      </div>

      <div className="min-h-0">
        <TelemetryStrip />
      </div>

      <motion.footer
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.8, delay: FOOTER_DELAY_S }}
        className="label-micro flex flex-wrap items-center justify-between gap-x-6 gap-y-1.5 px-1 tracking-normal normal-case"
      >
        <span>api {BACKEND_URL}</span>
        <span>physical_layer &lt;-&gt; rosbridge :9090</span>
        <span>build {BUILD_TAG}</span>
      </motion.footer>
    </main>
  )
}
