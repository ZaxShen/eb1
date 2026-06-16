import { defineConfig, devices } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/**
 * Self-booting E2E harness: a real browser drives the real Vite frontend, which
 * proxies /api to the real FastAPI backend, which reads a freshly SEEDED
 * PostgreSQL database. Nothing here touches the repo's real datasets, MongoDB,
 * an LLM, or the network.
 *
 * webServer boots, in order:
 *   1. backend — brings up the docker Postgres (annotation/docker-compose.yml),
 *      applies the schema + seeds the fixture (no LLM), then runs `uvicorn` on
 *      port 8200 with EB1_ANNOTATION_DSN pointed at that database;
 *   2. frontend — `vite` dev server on the test port, proxying /api -> 8200.
 *
 * `reuseExistingServer: !CI` so local reruns are fast; CI always boots fresh.
 */

const CI = !!process.env.CI;

const BACKEND_PORT = 8200;
const FRONTEND_PORT = 5273;

const REPO_ROOT = path.resolve(__dirname, "../..");
const COMPOSE_FILE = "annotation/docker-compose.yml";
const SEED_SCRIPT = "annotation/frontend/e2e/fixtures/seed_e2e.py";

// The annotation backend + seed both read this. Kept in sync with the default
// in annotation/backend/config.py and the docker-compose host port.
const ANNOTATION_DSN =
  process.env.EB1_ANNOTATION_DSN ??
  "postgresql://eb1:eb1@localhost:5544/eb1_annotation";

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
      // Bring up Postgres, apply schema + seed the fixture, then start the
      // backend pointed at it. The seed runs every boot so the dataset is
      // deterministic and self-contained.
      command:
        `docker compose -f ${COMPOSE_FILE} up -d --wait && ` +
        `uv run python ${SEED_SCRIPT} && ` +
        `uv run uvicorn annotation.backend.app:app --port ${BACKEND_PORT}`,
      cwd: REPO_ROOT,
      url: `http://localhost:${BACKEND_PORT}/api/datasets`,
      timeout: 180_000,
      reuseExistingServer: !CI,
      env: { EB1_ANNOTATION_DSN: ANNOTATION_DSN },
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
