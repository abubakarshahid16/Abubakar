import { defineConfig, devices } from "@playwright/test";

/**
 * The Chat screen, end to end in a real browser, against a MOCKED API.
 *
 * No backend, no model and no documents: every /api call is answered by the
 * spec itself (page.route), so this runs anywhere the frontend builds - CI
 * included - and never touches client data. What it proves is the browser
 * half: streaming, Stop, sources, drafts, web consent and recent chats work
 * as a person uses them. The backend halves are proven by pytest.
 */
export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: /chat-redesign\.spec\.ts$/,
  fullyParallel: false,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"],
    // A machine with a pre-installed browser of another build points at it;
    // CI installs the matching one and leaves this unset.
    launchOptions: process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {},
  },
  webServer: {
    command: "npm run dev -- --host 127.0.0.1",
    cwd: ".",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
