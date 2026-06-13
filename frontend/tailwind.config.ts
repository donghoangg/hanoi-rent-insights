import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // Bảng màu đồng nhất với dashboard Streamlit (3_Phan_tich.py)
        accent: "#2563eb",
        "accent-soft": "#93c5fd",
        good: "#16a34a",
        bad: "#dc2626",
        ink: {
          900: "#0f172a",
          800: "#1e293b",
          700: "#334155",
          500: "#64748b",
          400: "#94a3b8",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};

export default config;
