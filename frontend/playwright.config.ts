import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  reporter: "list",
  use: { baseURL: "http://127.0.0.1:5173", trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    { command: ".venv\\Scripts\\python.exe backend\\run.py", cwd: "..", env: { AUTH_MODE: "demo_required", AUTH_SECRET: "playwright-test-secret-012345678901234567890123456789" }, url: "http://127.0.0.1:8000/api/health", reuseExistingServer: true, timeout: 120_000 },
    { command: "npm run dev -- --host 127.0.0.1", cwd: ".", url: "http://127.0.0.1:5173", reuseExistingServer: true, timeout: 120_000 },
  ],
});
