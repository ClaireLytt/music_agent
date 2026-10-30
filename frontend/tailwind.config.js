/** 设计 token 来源：DESIGN.md / prototypes/canon_mv_player.html */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#121212",
        bg2: "#181818",
        deep: "#0c0c0e",
        panel: "#1e1e22",
        panel2: "#24242a",
        line: "#232329",
        edge: "#2a2a31",
        edge2: "#2e2e36",
        ink: "#f5f5f4",
        ink2: "#a8a8b3",
        ink3: "#a8a8b3",
        accent: "#7c9eff",
        "accent-soft": "rgba(124,158,255,.16)",
      },
      fontFamily: {
        sans: ["Inter", "Noto Sans SC", "system-ui", "sans-serif"],
      },
      borderRadius: { card: "12px" },
      boxShadow: {
        mv: "0 18px 40px -18px rgba(0,0,0,.65)",
        art: "0 6px 16px -6px rgba(0,0,0,.6)",
        pop: "0 14px 32px -14px rgba(0,0,0,.75)",
      },
      keyframes: {
        headshake: {
          "0%, 100%": { transform: "translateX(0)" },
          "20%": { transform: "translateX(-4px)" },
          "40%": { transform: "translateX(4px)" },
          "60%": { transform: "translateX(-2px)" },
          "80%": { transform: "translateX(2px)" },
        },
        popin: {
          from: { opacity: "0", transform: "translate(-50%, 4px)" },
          to: { opacity: "1", transform: "translate(-50%, 0)" },
        },
      },
      animation: {
        headshake: "headshake .4s ease",
        popin: "popin .18s cubic-bezier(.16,1,.3,1) both",
      },
    },
  },
  plugins: [],
};
