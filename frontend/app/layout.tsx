import type { Metadata } from "next";
import "./globals.css";
import { AuthGuard } from "@/components/AuthGuard";
import { LayoutShell } from "@/components/LayoutShell";
import { ThemeProvider } from "@/components/ThemeProvider";
import { UpgradeModal } from "@/components/UpgradeModal";

export const metadata: Metadata = {
  title: "MarketLens — AI Trading Terminal",
  description: "Multi-layer decision pipeline: Technical · SMC · Gann · Fibonacci · F&O analytics · Vedic timing.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Pre-paint theme — prevents light/dark flash on first load */}
        <script dangerouslySetInnerHTML={{ __html: `
          try {
            var s = localStorage.getItem('marketlens_theme');
            if (!s) s = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
            if (s === 'dark') document.documentElement.classList.add('dark');
          } catch (e) {}
        ` }} />
        {/* Inter Variable + JetBrains Mono Variable — modern, free, optimized
            for tabular financial data. Variable fonts cut font-file count and
            enable per-weight tuning via font-variation-settings. */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <ThemeProvider>
          <AuthGuard>
            <LayoutShell>{children}</LayoutShell>
          </AuthGuard>
          {/* Global modal — listens for 402 responses and shows tier ladder */}
          <UpgradeModal />
        </ThemeProvider>
      </body>
    </html>
  );
}
