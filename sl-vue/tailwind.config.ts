import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{vue,ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#f7f5fa",
          100: "#eee9f3",
          500: "#7c5ec4",
          600: "#6b4cb6",
          700: "#583b9c",
        },
        canvas: {
          bg: "#fafaf9",
          node: "#ffffff",
          border: "#e7e5e4",
          dirty: "#dc2626",
          locked: "#16a34a",
        },
      },
      fontFamily: {
        sans: ['"PingFang SC"', "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
} satisfies Config;
