import { setupServer } from "msw/node";
import { handlers } from "./handlers";

// Node MSW server shared by the vitest run. Lifecycle (listen / resetHandlers /
// close) is wired in src/test/setup.ts so component tests just import the
// handlers (or override per-test via server.use(...)).
export const server = setupServer(...handlers);
