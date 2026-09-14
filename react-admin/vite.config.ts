import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev-only proxy so the SPA can call the smart-llm API same-origin at /api.
// Point VITE_API_TARGET at your running smart-llm service.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: process.env.VITE_API_TARGET || "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
