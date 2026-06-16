import { expect, test } from "@playwright/test";
import { AnnotationPage } from "../pages/AnnotationPage";

/**
 * Taxonomy-management flow, end-to-end against the live backend + seeded
 * Postgres: open the manager, add a new topic, inline-rename it, and confirm the
 * renamed name is reflected in the manager list. The add + rename both target the
 * `user` taxonomy namespace and use a unique slug, so the test is self-contained
 * and order-independent. It deletes the topic it created to leave the fixture clean.
 *
 * Founder priority: proposing a new topic and renaming one must feel smooth — this
 * spec exercises exactly that path through the real CRUD endpoints.
 */

const WILDCHAT = "wildchat";
const ADDED = "e2e_propose_topic";
const RENAMED = "e2e_renamed_topic";

test.describe("taxonomy management flow", () => {
  test("open manager → add a topic → rename → reflected in the list", async ({
    page,
  }) => {
    const app = new AnnotationPage(page);
    await app.goto();
    await app.selectDataset(WILDCHAT);

    await app.openTaxonomyManager();

    // Propose a new topic; it appears in the list (display-cased) after refetch.
    await app.addTaxonomyTopic(ADDED);
    await expect(app.taxonomyRow("E2e Propose Topic")).toBeVisible();

    // Inline-rename it; the new name replaces the old in the list.
    await app.renameTaxonomyTopic(ADDED, RENAMED);
    await expect(app.taxonomyRow("E2e Renamed Topic")).toBeVisible();
    await expect(app.taxonomyRow("E2e Propose Topic")).toHaveCount(0);

    // Clean up: delete the topic this test created so the fixture stays pristine.
    await page
      .getByRole("dialog", { name: "Manage taxonomy" })
      .getByRole("button", { name: `Delete ${RENAMED}` })
      .click();
    await expect(app.taxonomyRow("E2e Renamed Topic")).toHaveCount(0);
  });
});
