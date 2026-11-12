import type { Metadata, Viewport } from "next";

import { Providers } from "./providers";

import "./globals.css";

export const metadata: Metadata = {
  title: "TaskPilot AI",
  description: "Voice-controlled autonomous browser agent — Phase 1 control dashboard.",
  icons: { icon: [{ url: "/favicon.ico" }, { url: "/logo.svg", type: "image/svg+xml" }] },
};

export const viewport: Viewport = {
  themeColor: "#05070d",
  colorScheme: "dark",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
