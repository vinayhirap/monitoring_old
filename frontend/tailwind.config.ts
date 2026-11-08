import type { Config } from "tailwindcss";

const config: Config = {
  // `darkMode: 'class'` — Tailwind toggles dark variants when <html> has .dark
  darkMode: "class",
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      // ── Colors driven entirely by CSS variables in globals.css ──
      // Light + dark themes share the same Tailwind class names; only the
      // underlying variable changes. So `bg-bg-panel` is white in light
      // mode and dark blue in dark mode automatically.
      colors: {
        bg: {
          base:    "var(--bg-base)",
          surface: "var(--bg-surface)",
          panel:   "var(--bg-panel)",
          panel2:  "var(--bg-panel2)",
          line:    "var(--bg-line)",
          lineHi:  "var(--bg-line-hi)",
        },
        accent: {
          amber:     "var(--accent-amber)",
          gold:      "var(--accent-gold)",
          green:     "var(--accent-green)",
          greenSoft: "var(--accent-green-soft)",
          red:       "var(--accent-red)",
          redSoft:   "var(--accent-red-soft)",
          blue:      "var(--accent-blue)",
          cyan:      "var(--accent-cyan)",
          violet:    "var(--accent-violet)",
          pink:      "var(--accent-pink)",
        },
        text: {
          primary:   "var(--text-primary)",
          secondary: "var(--text-secondary)",
          muted:     "var(--text-muted)",
        },
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system",
                "Segoe UI", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular",
                "Menlo", "Monaco", "Consolas", "monospace"],
      },
      boxShadow: {
        glow:       "var(--shadow-glow)",
        glowGreen:  "0 0 14px rgba(10, 143, 96, 0.28)",
        glowRed:    "0 0 14px rgba(200, 41, 74, 0.28)",
        glowViolet: "0 0 14px rgba(124, 58, 237, 0.28)",
        card:       "var(--shadow-card)",
        cardHover:  "var(--shadow-card-hover)",
      },
      keyframes: {
        shimmer: {
          "0%":   { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
        ticker: {
          "0%":   { transform: "translateX(0)" },
          "100%": { transform: "translateX(-50%)" },
        },
        flash: {
          "0%, 100%": { backgroundColor: "transparent" },
          "50%":      { backgroundColor: "rgba(196, 114, 13, 0.18)" },
        },
        "fade-in": {
          "0%":   { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        shimmer:  "shimmer 1.6s linear infinite",
        ticker:   "ticker 40s linear infinite",
        flash:    "flash 1.2s ease-out",
        "fade-in": "fade-in 200ms ease-out",
      },
    },
  },
  plugins: [],
};
export default config;
