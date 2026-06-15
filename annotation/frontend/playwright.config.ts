import { defineConfig, devices } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/**
 * Self-booting E2E harness: a real browser drives the real Vite frontend, which
 * proxies /api to the real FastAPI backend, which reads a freshly SEEDED SQLite
 * fixture tree. Nothing here touches the repo's real `datasets/`, MongoDB,
 * Postgres, an LLM, or the network.
 *
 * webServer boots, in order:
 *   1. backend — seeds the fixture (mock analyzer, no LLM) then `uvicorn` on
 *      port 8200 with EB1_DATASETS_DIR pointed at the fixture;
 *   2. frontend — `vite` dev server on the test port, proxying /api -> 8200.
 *
 * `reuseExistingServer: !CI` so local reruns are fast; CI always boots fresh.
 */

const CI = !!process.env.CI;

const BACKEND_PORT = 8200;
const FRONTEND_PORT = 5273;

const REPO_ROOT = path.resolve(__dirname, "../..");
const FIXTURE_DIR = path.resolve(__dirname, "e2e/.datasets");
const SEED_SCRIPT = "annotation/frontend/e2e/fixtures/seed_e2e.py";

export default defineConfig({
  testDir: "./e2e/specs",
  fullyParallel: true,
  forbidOnly: CI,
  retries: CI ? 1 : 0,
  reporter: CI ? "github" : [["list"]],
  use: {
    baseURL: `http://localhost:${FRONTEND_PORT}`,
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      // Seed a fresh fixture, then start the backend pointed at it. The seed
      // runs every boot so the dataset is deterministic and self-contained.
      command:
        `uv run python ${SEED_SCRIPT} --out "${FIXTURE_DIR}" && ` +
        `uv run uvicorn annotation.backend.app:app --port ${BACKEND_PORT}`,
      cwd: REPO_ROOT,
      url: `http://localhost:${BACKEND_PORT}/api/datasets`,
      timeout: 180_000,
      reuseExistingServer: !CI,
      env: { EB1_DATASETS_DIR: FIXTURE_DIR },
    },
    {
      command: "npm run dev",
      url: `http://localhost:${FRONTEND_PORT}`,
      timeout: 120_000,
      reuseExistingServer: !CI,
      env: {
        VITE_PORT: String(FRONTEND_PORT),
        VITE_API_PORT: String(BACKEND_PORT),
      },
    },
  ],
});
