import { expect, test } from "@playwright/test";
import { AnnotationPage } from "../pages/AnnotationPage";

/**
 * The per-labeler labeling flow (SuperDialseg decision #73), end-to-end against the
 * live backend + seeded Postgres: pick a labeler slot, open the conversation that
 * slot is assigned, relabel a segment by picking a taxonomy topic from the True
 * Topic dropdown, and confirm it persists (the segment flips to reviewed).
 *
 * Fixture (seed_e2e.py): the superdialseg dialogue `e2e_superdialseg_0001` is the
 * only row assigned to `labeler_a` in the seeded worklist, so picking that slot
 * narrows the queue to exactly it. superdialseg is the frozen, name-only dataset
 * the re-segment spec never touches, so this spec runs free of cross-file races.
 * The write mutates seeded gold, so the test reverts it (undo) to stay
 * order-independent.
 */

const SUPERDIALSEG = "superdialseg";
const ASSIGNED_CONV = "e2e_superdialseg_0001";

test.describe.configure({ mode: "serial" });

test.describe("per-labeler labeling flow", () => {
  test("pick labeler → open conv → label a segment → persisted", async ({
    page,
  }) => {
    const app = new AnnotationPage(page);
    await app.goto();
    await app.selectDataset(SUPERDIALSEG);

    // Picking labeler_a filters the queue to that slot's single worklist row.
    await app.selectLabeler("labeler_a");
    await expect(app.conversation(ASSIGNED_CONV)).toBeVisible();
    await expect.poll(() => app.conversations().count()).toBe(1);

    await app.openConversation(ASSIGNED_CONV);
    await app.selectSegment(0);
    expect(await app.fieldValue("reviewed")).toBe("No");

    // Relabel the segment by picking a seeded taxonomy topic (slug) from the
    // True Topic dropdown, then persist it.
    await app.selectTopic("cover_letter_help");
    await app.save();

    // Persisted: the effective segment comes back reviewed.
    await expect.poll(() => app.fieldValue("reviewed")).toBe("Yes");

    // Revert so the fixture returns to its seeded unreviewed state.
    await app.undo();
    await expect.poll(() => app.fieldValue("reviewed")).toBe("No");
  });
});
