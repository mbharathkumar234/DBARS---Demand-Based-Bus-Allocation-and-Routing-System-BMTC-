import type { Config } from "tailwindcss";

export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: "var(--surface)",
        "surface-2": "var(--surface-strong)",
        primary: "var(--brand)",
        "primary-hover": "var(--brand-strong)",
        border: "var(--line-strong)",
        "text-1": "var(--text)",
        "text-2": "var(--text-2)",
        "text-3": "var(--muted)"
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "Segoe UI", "sans-serif"]
      },
      boxShadow: {
        glow: "0 24px 70px rgba(14, 116, 144, 0.24)"
      }
    }
  },
  plugins: []
} satisfies Config;
