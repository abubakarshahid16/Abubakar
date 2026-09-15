import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    exclude: ["tests/e2e/**", "node_modules/**"],
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    // Vitest 5 defaults hooks to parallel. Testing Library's automatic React
    // cleanup must finish before per-test global fetch mocks are restored,
    // otherwise an unmounting polling view can call the next test's mock.
    sequence: { hooks: "list", concurrent: false },
  },
});
