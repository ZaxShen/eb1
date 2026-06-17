import { expect, test } from "@playwright/test";
import { AnnotationPage } from "../pages/AnnotationPage";

/**
 * BERTopic queue filter (issue 20, decision #87), end-to-end against the live
 * backend + seeded Postgres: pick a BERTopic topic in the queue dropdown and
 * confirm the conversation list narrows to the conversation whose gold segment
 * carries that BERTopic label.
 *
 * Fixture (seed_e2e.py): the superdialseg conversation `e2e_superdialseg_0002`
 * gets one whole-conversation `source='gold'` segment labeled with the BERTopic
 * topic `billing_disputes` — and it's the only one — so picking that topic
 * leaves exactly that single card. It's a conversation the labeling/operations
 * specs never open, so the injected gold stays inert for them.
 */

const SUPERDIALSEG = "superdialseg";
const BILLING_CONV = "e2e_superdialseg_0002";

test.describe("BERTopic queue filter", () => {
  test("pick a BERTopic topic → queue narrows to its conversations", async ({
    page,
  }) => {
    const app = new AnnotationPage(page);
    await app.goto();
    await app.selectDataset(SUPERDIALSEG);

    // Both superdialseg conversations are present before filtering.
    await expect(app.conversation(BILLING_CONV)).toBeVisible();
    await expect.poll(() => app.conversations().count()).toBeGreaterThan(1);

    await app.selectBertopicTopic(/Billing Disputes/);

    // Only the conversation labeled `billing_disputes` survives the filter.
    await expect(app.conversation(BILLING_CONV)).toBeVisible();
    await expect.poll(() => app.conversations().count()).toBe(1);
  });
});
