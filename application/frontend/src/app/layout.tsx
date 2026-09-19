import type { ReactNode } from "react"
import type { Metadata, Viewport } from "next"
import { Fragment_Mono, Inter } from "next/font/google"

import { Providers } from "@/components/providers"

import "./globals.css"

const inter = Inter({ variable: "--font-inter", subsets: ["latin"], display: "swap" })

const fragmentMono = Fragment_Mono({
  variable: "--font-fragment-mono",
  subsets: ["latin"],
  weight: "400",
  display: "swap",
})

export const metadata: Metadata = {
  title: "HTN - Hand Console",
  description:
    "Live simulator console for the exoskeleton hand: 3D hand viewport, RealSense color and depth views, per-finger telemetry.",
}

export const viewport: Viewport = {
  themeColor: "#f6f6f6",
  colorScheme: "light",
}

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${fragmentMono.variable} antialiased`}>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  )
}
