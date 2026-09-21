import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    // The dev proxy target is configurable so a second backend - one with
    // AUTH_MODE disabled, say, for a screenshot or a smoke run - can be
    // pointed at without editing this file. Defaults to the ordinary one.
    proxy: { "/api": process.env.VITE_API_TARGET ?? "http://127.0.0.1:8000" },
    fs: { allow: [".."] },
  },
});
