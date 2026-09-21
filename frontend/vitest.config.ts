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
    // THE FLAKE WAS MEMORY, AND THE WORKER COUNT IS THE FIX. Measured on
    // this machine 2026-09-19 - the laptop is production, so its limits are
    // the ones that matter - with free RAM sampled every 0.8s through a run:
    //
    //   workers   wall   LOWEST FREE RAM   result
    //   default    93s          147 MB     1 failed
    //   4          95s        1,648 MB     673/673
    //
    // vitest's default starts roughly one jsdom worker per core (12 here),
    // and the machine idles with ~2.6 GB free. The default run drove it to
    // 147 MB, Windows paged, and renders stalled for SECONDS - so tests
    // crossed both timing budgets at once: `testTimeout` (5s) and a
    // `findBy`'s own 1s wait. That is why the failures moved between files
    // from run to run, why they landed on the FIRST test of heavy files (a
    // worker's most memory-hungry moment: module evaluation plus the first
    // render), and why one run took 216s for a file that normally takes 60s.
    //
    // A FIRST ATTEMPT RAISED `testTimeout` TO 15s, AND IT WAS WRONG. It
    // treated the symptom: the next run failed anyway, on `findBy`'s 1s
    // budget in a different file, because the stall was never in the test.
    // Instrumentation of IngestionView.watch then showed the heading
    // genuinely ABSENT 1.3s after mount - with a mock that resolves on the
    // next microtask - which is not a slow query; it is a starved process.
    // Capping workers costs nothing in wall time here, because the default
    // was already spending that time paging.
    maxWorkers: 4,
  },
});
