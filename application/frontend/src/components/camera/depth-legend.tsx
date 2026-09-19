import { DEPTH_GRADIENT } from "@/lib/depth-ramp"

const TICKS = 5

/** Vertical colormap scale, far at the top, labelled in metres. */
export function DepthLegend({ minMm, maxMm }: { minMm: number; maxMm: number }) {
  const ticks = Array.from({ length: TICKS }, (_, i) => maxMm - ((maxMm - minMm) * i) / (TICKS - 1))

  return (
    <div className="flex h-full flex-col gap-2">
      <span className="label-micro">Range m</span>
      <div className="flex min-h-0 flex-1 gap-1.5">
        <div className="w-1.5 shrink-0 border border-hairline bg-no-repeat bg-origin-border" style={{ backgroundImage: DEPTH_GRADIENT }} />
        <ol className="relative flex-1">
          {ticks.map((mm, i) => (
            <li
              key={mm}
              className="absolute left-0 flex -translate-y-1/2 items-center gap-1"
              style={{ top: `${(i / (TICKS - 1)) * 100}%` }}
            >
              <span aria-hidden className="h-px w-1.5 bg-ink-mute" />
              <span className="num text-[10px] leading-none text-ink-soft">{(mm / 1000).toFixed(2)}</span>
            </li>
          ))}
        </ol>
      </div>
      <span className="label-micro flex items-center gap-1.5">
        <span aria-hidden className="size-1.5 border border-hairline bg-page" />
        Void
      </span>
    </div>
  )
}
