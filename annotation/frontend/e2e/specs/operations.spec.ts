import { expect, test } from "@playwright/test";
import { AnnotationPage } from "../pages/AnnotationPage";

/**
 * The re-segment regression suite — the tests that would have caught the
 * original bug. Each drives a real boundary/relabel write through the live
 * backend and asserts the stream re-renders the EFFECTIVE segmentation that
 * Task A now returns as `segments`. Before the fix the stream rendered the
 * predicted field and ignored every edit, so all four of these would fail.
 *
 * Fixture (seed_e2e.py via the mock analyzer): the wildchat conversation
 * `e2ewild0000000a1` is one machine segment spanning its four messages —
 * the ideal split/merge subject. Each test opens it fresh; gold edits persist
 * to the seeded SQLite, so a test reverts what it writes (merge after split;
 * undo) to keep the suite order-independent.
 */

const WILDCHAT = "wildchat";
const CONV = "e2ewild0000000a1";
const UNREVIEWED_CONV = "e2ewild0000000b2";
const SPLIT_AT = "How far away is the Andromeda";

async function open(page: import("@playwright/test").Page, conv = CONV) {
  const app = new AnnotationPage(page);
  await app.goto();
  await app.selectDataset(WILDCHAT);
  await app.openConversation(conv);
  return app;
}

// These specs mutate shared backend gold state (one seeded SQLite fixture), so
// they run serially and each reverts its own write — keeping every assertion
// (segment counts, reviewed stat) deterministic regardless of order.
test.describe.configure({ mode: "serial" });

test.describe("re-segment operations (effective segmentation)", () => {
  // Runs first (serial order) so the seeded UNREVIEWED conversation is the only
  // moving part: no boundary write from a sibling test has touched the dataset's
  // reviewed set yet, making the stat delta a clean +1.
  test("RELABEL + Save marks the segment reviewed and bumps the stat", async ({
    page,
  }) => {
    const app = await open(page, UNREVIEWED_CONV);
    await app.selectSegment(0);
    expect(await app.fieldValue("reviewed")).toBe("No");

    const before = await app.statsReviewed();

    // Confirm AI copies the segment's predicted label into the True Topic, then
    // Save persists it as a human relabel against the effective segment.
    await page.getByRole("button", { name: /Confirm AI/ }).click();
    await app.save();

    await expect.poll(() => app.statsReviewed()).toBe(before + 1);
    // The reloaded segment shows reviewed in the fields panel.
    await expect.poll(() => app.fieldValue("reviewed")).toBe("Yes");

    // Revert so the fixture returns to its seeded unreviewed state.
    await app.undo();
    await expect.poll(() => app.fieldValue("reviewed")).toBe("No");
  });

  test("SPLIT adds a labeled segment divider and increases the count", async ({
    page,
  }) => {
    const app = await open(page);
    const before = await app.segmentCount();

    await app.splitAt(0, SPLIT_AT);

    // The stream re-renders the effective set: one more segment, one more
    // labeled divider — the split is reflected, not swallowed.
    await expect.poll(() => app.segmentCount()).toBe(before + 1);
    await expect(app.segments().nth(before)).toBeVisible();
    // Split children inherit the parent topic (not an empty "No topic" label).
    expect(await app.untopicedSegments()).toBe(0);

    // Revert (merge back) so the conversation returns to its seeded shape.
    await app.mergeSegment(1);
    await expect.poll(() => app.segmentCount()).toBe(before);
  });

  test("MERGE decreases the rendered segment count", async ({ page }) => {
    const app = await open(page);
    const base = await app.segmentCount();

    // Split first so there is an adjacent segment to merge back.
    await app.splitAt(0, SPLIT_AT);
    await expect.poll(() => app.segmentCount()).toBe(base + 1);

    await app.mergeSegment(1);
    await expect.poll(() => app.segmentCount()).toBe(base);
  });

  test("UNDO a split restores the original boundaries", async ({ page }) => {
    const app = await open(page);
    const before = await app.segmentCount();

    await app.splitAt(0, SPLIT_AT);
    await expect.poll(() => app.segmentCount()).toBe(before + 1);

    await app.undo();
    await expect.poll(() => app.segmentCount()).toBe(before);
  });
});
