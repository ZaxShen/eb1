import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: Number(process.env.VITE_PORT ?? 5173),
    proxy: {
      "/api": {
        target: `http://localhost:${process.env.VITE_API_PORT ?? 8000}`,
        changeOrigin: true,
      },
    },
  },
});
