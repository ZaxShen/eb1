import { expect, type Locator, type Page } from "@playwright/test";

/**
 * Page object for the UFL Annotation app.
 *
 * Encapsulates every interaction the annotation UI supports so specs read as
 * intent ("open this conversation, split here, save") rather than selectors.
 * Methods are provided for the FULL feature surface — split/merge/relabel/
 * undo/redo/stats — even where the current smoke specs don't exercise them, so
 * future specs (e.g. the re-segment regression) reuse them unchanged.
 *
 * Selectors lean on accessible roles and stable visible text rather than
 * test-only attributes, so the harness stays decoupled from styling churn.
 */
export class AnnotationPage {
  readonly page: Page;

  constructor(page: Page) {
    this.page = page;
  }

  async goto(): Promise<void> {
    await this.page.goto("/");
    await expect(this.heading()).toBeVisible();
  }

  heading(): Locator {
    return this.page.getByRole("heading", { name: "UFL Annotation" });
  }

  // --- Dataset selection -------------------------------------------------

  private datasetTrigger(): Locator {
    return this.page.getByRole("combobox").first();
  }

  /** Currently-selected dataset name shown on the dataset combobox. */
  async currentDataset(): Promise<string> {
    return (await this.datasetTrigger().textContent())?.trim() ?? "";
  }

  /** Open the dataset dropdown and choose `name`, waiting for the swap. */
  async selectDataset(name: string): Promise<void> {
    await this.datasetTrigger().click();
    await this.page.getByRole("option", { name, exact: true }).click();
    await expect(this.datasetTrigger()).toContainText(name);
  }

  // --- Conversation queue ------------------------------------------------

  /** Locator over the conversation queue cards. Each card button carries the
   * "<n> msg" message-count line, which the filter/pagination controls don't —
   * so this never picks up the search/status/page buttons in the queue. */
  conversations(): Locator {
    return this.page.getByRole("button").filter({ hasText: /\d+ msg/ });
  }

  /** A single conversation card located by its conversation id text. */
  conversation(id: string): Locator {
    return this.page.getByRole("button", { name: new RegExp(id) });
  }

  /** Click a conversation card and wait for its stream to render. */
  async openConversation(id: string): Promise<void> {
    await this.conversation(id).click();
    await expect(this.segments().first()).toBeVisible();
  }

  // --- Queue search + pagination -----------------------------------------

  searchBox(): Locator {
    return this.page.getByRole("searchbox", { name: /search conversations/i });
  }

  /** Type a query into the debounced queue search. */
  async searchConversations(query: string): Promise<void> {
    const box = this.searchBox();
    await box.click();
    await box.fill(query);
  }

  /** Clear the queue search box. */
  async clearSearch(): Promise<void> {
    await this.searchBox().fill("");
  }

  async nextPage(): Promise<void> {
    await this.page.getByRole("button", { name: "Next page" }).click();
  }

  async prevPage(): Promise<void> {
    await this.page.getByRole("button", { name: "Previous page" }).click();
  }

  /** The "<start>–<end> of <total>" range text shown in the queue footer. */
  async queueRange(): Promise<string> {
    const text =
      (await this.page.getByText(/\d[\d,]*\s+of\s+[\d,]+/).first().textContent()) ??
      "";
    return text.trim();
  }

  // --- Segment stream ----------------------------------------------------

  /** Locator over the rendered segment dividers in the stream. */
  segments(): Locator {
    return this.page.locator("text=/^(Segment \\d+|Selected)$/");
  }

  /** Number of segments currently rendered in the stream. */
  async segmentCount(): Promise<number> {
    return this.segments().count();
  }

  /**
   * The divider row for the i-th (0-based) segment: the element wrapping the
   * "Segment N"/"Selected" label, which also holds that segment's merge control.
   */
  private dividerRow(i: number): Locator {
    return this.segments().nth(i).locator("xpath=ancestor::div[1]");
  }

  /** How many dividers render the "No topic" placeholder (an empty label). */
  async untopicedSegments(): Promise<number> {
    return this.page.getByText("No topic", { exact: true }).count();
  }

  /** Click the i-th (0-based) segment in the stream to select it. */
  async selectSegment(i: number): Promise<void> {
    await this.segments().nth(i).click();
    await expect(this.page.getByText("Selected", { exact: true })).toBeVisible();
  }

  /**
   * Split a segment at the message bubble whose text contains `text`: the
   * scissors control on that bubble starts a new segment there.
   *
   * The control is revealed on hover (`opacity-0` until `group-hover`), so we
   * hover the bubble and force the click rather than waiting on the fade-in.
   */
  async splitAt(_i: number, text: string): Promise<void> {
    const bubble = this.page.getByText(text, { exact: false }).first();
    await bubble.hover();
    const row = bubble.locator("xpath=ancestor::div[contains(@class,'gap-1')][1]");
    await row.getByRole("button").first().click({ force: true });
  }

  /** Merge the i-th (0-based, i>=1) segment into the previous one. */
  async mergeSegment(i: number): Promise<void> {
    const row = this.dividerRow(i);
    await row.hover();
    await row.getByRole("button").first().click({ force: true });
  }

  // --- Right-hand segment fields panel -----------------------------------

  /** The `<dd>` value cell for the named field in the Segment Fields panel. */
  field(label: string): Locator {
    return this.page.locator(
      `xpath=//dt[normalize-space()='${label}']/following-sibling::dd[1]`,
    );
  }

  async fieldValue(label: string): Promise<string> {
    return (await this.field(label).textContent())?.trim() ?? "";
  }

  // --- Annotation panel (relabel + save) ---------------------------------

  /** Set the True Topic and True Subtopic selects in the annotation panel. */
  async relabel(topic: string, sub?: string): Promise<void> {
    const panel = this.page
      .getByRole("heading", { name: "Annotation" })
      .locator("xpath=ancestor::div[1]");
    await panel.getByRole("combobox").first().click();
    await this.page.getByRole("option", { name: topic, exact: true }).click();
    if (sub !== undefined) {
      await panel.getByRole("combobox").nth(1).click();
      await this.page.getByRole("option", { name: sub, exact: true }).click();
    }
  }

  /** Click Save (persist the current annotation). */
  async save(): Promise<void> {
    await this.page.getByRole("button", { name: "Save" }).click();
  }

  // --- History -----------------------------------------------------------

  async undo(): Promise<void> {
    await this.page.getByRole("button", { name: "Undo" }).click();
  }

  async redo(): Promise<void> {
    await this.page.getByRole("button", { name: "Redo" }).click();
  }

  // --- Statistics --------------------------------------------------------

  /** The "<n> reviewed" count from the Statistics panel.
   *
   * Scoped to the Statistics card and anchored to the exact "<n> reviewed"
   * badge so it never picks up the queue cards' "x/y reviewed" totals. */
  async statsReviewed(): Promise<number> {
    const panel = this.page
      .getByRole("heading", { name: "Statistics" })
      .locator("xpath=ancestor::div[1]");
    const text =
      (await panel.getByText(/^\d+ reviewed$/).first().textContent()) ?? "0";
    return Number(text.replace(/\D+/g, ""));
  }
}
