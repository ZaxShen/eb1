import { expect, test } from "@playwright/test";
import { AnnotationPage } from "../pages/AnnotationPage";

/**
 * GREEN smoke specs — only flows that work today against the seeded fixture.
 *
 * Fixture (built by e2e/fixtures/seed_e2e.py via the mock analyzer): two
 * datasets, two conversations each, one segment per conversation.
 *
 * Deliberately does NOT assert the broken re-segment behavior — that's the next
 * increment, which will reuse this harness to expose and fix it.
 */

const WILDCHAT_CONV = "e2ewild0000000a1";

test.describe("annotation app smoke", () => {
  test("app loads with its heading and a dataset selected", async ({ page }) => {
    const app = new AnnotationPage(page);
    await app.goto();
    await expect(app.heading()).toBeVisible();
    // The first dataset auto-selects once /api/datasets resolves.
    await expect.poll(() => app.currentDataset()).not.toBe("");
  });

  test("switches between wildchat and superdialseg datasets", async ({
    page,
  }) => {
    const app = new AnnotationPage(page);
    await app.goto();

    await app.selectDataset("wildchat");
    expect(await app.currentDataset()).toBe("wildchat");

    await app.selectDataset("superdialseg");
    expect(await app.currentDataset()).toBe("superdialseg");

    await app.selectDataset("wildchat");
    expect(await app.currentDataset()).toBe("wildchat");
  });

  test("opening a conversation renders its segments", async ({ page }) => {
    const app = new AnnotationPage(page);
    await app.goto();
    await app.selectDataset("wildchat");

    // Read the backend's own segment_count off the queue card so the assertion
    // tracks the fixture rather than a hardcoded N.
    const card = app.conversation(WILDCHAT_CONV);
    await expect(card).toBeVisible();
    const cardText = (await card.textContent()) ?? "";
    const expected = Number(/(\d+)\s+segment/.exec(cardText)?.[1] ?? "0");
    expect(expected).toBeGreaterThan(0);

    await app.openConversation(WILDCHAT_CONV);
    expect(await app.segmentCount()).toBe(expected);
  });

  test("selecting a segment shows its id and message_indices", async ({
    page,
  }) => {
    const app = new AnnotationPage(page);
    await app.goto();
    await app.selectDataset("wildchat");
    await app.openConversation(WILDCHAT_CONV);
    await app.selectSegment(0);

    // The right-hand Segment Fields panel mirrors the selected segment.
    await expect(app.field("id")).toHaveText(/\d+/);
    await expect(app.field("message_indices")).toHaveText(/\[\d+(, \d+)*\]/);
    await expect(app.field("conversation")).toHaveText(WILDCHAT_CONV);
  });
});
