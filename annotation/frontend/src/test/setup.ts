import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll } from "vitest";
import { server } from "./msw/server";

// Component tests fetch through the relative `/api` proxy path; MSW (node)
// intercepts them. Unhandled requests error so a missing handler is loud, not
// a silent hang.
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
