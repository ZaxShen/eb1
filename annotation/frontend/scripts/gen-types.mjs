#!/usr/bin/env node
// Contract layer: dump the FastAPI OpenAPI schema, then generate frontend TS
// types from it. A field renamed on the backend changes schema.d.ts, so
// `types:check` (regen + `git diff --exit-code`) turns a silent frontend/backend
// drift into a failing build — the integration class the re-segment bug exposed.
//
// The schema is produced in-process (no uvicorn boot) by importing the app and
// calling app.openapi(); the JSON is committed at annotation/backend/openapi.json
// so CI and `types:check` are deterministic.

import { execFileSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_DIR = path.resolve(__dirname, "..");
const REPO_ROOT = path.resolve(FRONTEND_DIR, "../..");
const OPENAPI_JSON = path.resolve(REPO_ROOT, "annotation/backend/openapi.json");
const SCHEMA_OUT = path.resolve(FRONTEND_DIR, "src/api/schema.d.ts");

function run(cmd, args, opts = {}) {
  execFileSync(cmd, args, { stdio: "inherit", ...opts });
}

// 1. Export the live FastAPI schema to annotation/backend/openapi.json.
const dumpScript = [
  "import json, pathlib",
  "from annotation.backend.app import app",
  `out = pathlib.Path(${JSON.stringify(OPENAPI_JSON)})`,
  "out.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + '\\n')",
].join("; ");

run("uv", ["run", "python", "-c", dumpScript], { cwd: REPO_ROOT });

// 2. Generate frontend types from the committed schema.
mkdirSync(path.dirname(SCHEMA_OUT), { recursive: true });
run("npx", ["openapi-typescript", OPENAPI_JSON, "-o", SCHEMA_OUT], {
  cwd: FRONTEND_DIR,
});

console.log(`Wrote ${path.relative(REPO_ROOT, OPENAPI_JSON)} and ${path.relative(REPO_ROOT, SCHEMA_OUT)}`);
