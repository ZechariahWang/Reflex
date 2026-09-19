# frontend - HTN hand console

Next.js (App Router) + Tailwind v4 + shadcn/ui + motion + three.js (`@react-three/fiber`, `drei`, `urdf-loader`).
One screen: hand viewport, color + depth camera views, telemetry strip. Architecture and API: `../CONTRACT.md`.

```bash
cp .env.example .env.local   # NEXT_PUBLIC_BACKEND_URL, default http://localhost:8000
npm install
npm run dev                  # http://localhost:3000 (start ../backend first; MOCK=1 needs no ROS)
```

Shared code: `src/lib/{config,types,sim-store}.ts`, `src/hooks/use-camera-stream.ts`, `src/components/console/panel.tsx`; design tokens and the `label-micro` / `num` / `hairline-frame` / `bg-dot-grid` utilities live in `src/app/globals.css`.
