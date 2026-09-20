import * as motion from "motion/react-client"

import { ConsoleStage } from "@/components/console/console-stage"
import { EpisodeBar } from "@/components/console/episode-bar"
import { TopBar } from "@/components/console/top-bar"
import { BACKEND_URL } from "@/lib/config"

import packageJson from "../../package.json"

const BUILD_TAG = `v${packageJson.version}-${process.env.NODE_ENV === "production" ? "prod" : "dev"}`

/** Lands last: top bar at 0, panels 01-04 at 70 ms steps, then this line. */
const FOOTER_DELAY_S = 0.75

/**
 * In the `console` variant (>= 1024 x 640) the page is exactly one screen and the 3D hand is
 * the page: top bar / the stage (hand with the command block under it, RealSense over iPhone,
 * the mirror only while it is on) / episodes / footer line. Below that size it becomes a
 * normal scrolling column.
 */
export default function ConsolePage() {
  return (
    <main className="mx-auto flex min-h-dvh max-w-[2400px] flex-col gap-3 p-3 console:grid console:h-dvh console:grid-rows-[auto_minmax(0,1fr)_auto_auto] console:overflow-hidden">
      <TopBar />

      <ConsoleStage />

      <EpisodeBar />

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
