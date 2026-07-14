import { expect, type Locator, type Page } from "@playwright/test";

/**
 * Page object for the eb1 Annotation app.
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
    return this.page.getByRole("heading", { name: "eb1 Annotation" });
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

  // --- Labeler picker (per-labeler worklist) -----------------------------

  private labelerTrigger(): Locator {
    return this.page.getByRole("combobox", { name: "Labeler" });
  }

  /**
   * Pick a fetched worklist labeler value (e.g. "labeler_a"), filtering the
   * queue to that labeler's assignments. The options come from the dataset's
   * worklist (GET /datasets/{ds}/labelers), so `value` must match a value the
   * seed fixture assigns.
   */
  async selectLabeler(value: string): Promise<void> {
    await this.labelerTrigger().click();
    await this.page.getByRole("option", { name: value, exact: true }).click();
    await expect(this.labelerTrigger()).toContainText(value);
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

  /** Pick a BERTopic topic in the queue's BERTopic-topic dropdown, narrowing
   * the list to conversations whose gold segments carry that BERTopic label. */
  async selectBertopicTopic(label: RegExp | string): Promise<void> {
    await this.page.getByRole("combobox", { name: "BERTopic topic" }).click();
    await this.page.getByRole("option", { name: label }).click();
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

  /** The True Topic dropdown trigger (a Radix Select, role=combobox, labelled
   * by its aria-label). */
  private topicTrigger(): Locator {
    return this.page.getByRole("combobox", { name: "True Topic" });
  }

  /** Slug → display label, mirroring the frontend `formatLabel` (underscores →
   * spaces, Title Case): the dropdown renders labels while callers pass the
   * stored slug, so option lookups match the rendered text. */
  private slugLabel(slug: string): string {
    return slug.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  }

  /** Normalize a label to a lowercase snake_case slug — the mirror of the
   * backend `slugify` (annotation/backend/slug.py) and the panel's live
   * preview, so specs can predict the value a typed name is stored as. */
  private slugify(label: string): string {
    return label
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "");
  }

  /**
   * Pick an existing taxonomy option in the True Topic dropdown by its stored
   * slug. The Select renders each option's Title-Cased label, so this opens the
   * dropdown and clicks the option whose visible text is `slugLabel(slug)`.
   */
  async selectTopic(slug: string): Promise<void> {
    const label = this.slugLabel(slug);
    await this.topicTrigger().click();
    await this.page.getByRole("option", { name: label, exact: true }).click();
    await expect(this.topicTrigger()).toContainText(label);
  }

  /**
   * Add a brand-new topic through the dropdown's "+ New topic…" inline input:
   * open the Select, reveal the input, type `label`, assert the live slug
   * preview shows the normalized slug, then confirm. Returns the slug the value
   * is stored as (lowercase snake_case) so specs can assert on it.
   */
  async addNewTopic(label: string): Promise<string> {
    const slug = this.slugify(label);
    await this.topicTrigger().click();
    await this.page
      .getByRole("option", { name: "+ New topic…", exact: true })
      .click();
    await this.page
      .getByRole("textbox", { name: "True Topic new name" })
      .fill(label);
    // The panel previews the value it will store ("Saves as <slug>").
    await expect(
      this.page.locator("code").filter({ hasText: slug }),
    ).toBeVisible();
    await this.page
      .getByRole("button", { name: "Confirm new True Topic" })
      .click();
    return slug;
  }

  /** Click Save (persist the current annotation). */
  async save(): Promise<void> {
    await this.page.getByRole("button", { name: "Save" }).click();
  }

  // --- Taxonomy manager --------------------------------------------------

  /** Open the taxonomy-management dialog from the header. */
  async openTaxonomyManager(): Promise<Locator> {
    await this.page.getByRole("button", { name: "Manage taxonomy" }).click();
    const dialog = this.page.getByRole("dialog", { name: "Manage taxonomy" });
    await expect(dialog).toBeVisible();
    return dialog;
  }

  /** Add a topic via the manager's "Add topic" input. */
  async addTaxonomyTopic(name: string): Promise<void> {
    const dialog = this.page.getByRole("dialog", { name: "Manage taxonomy" });
    await dialog.getByLabel("New topic name").fill(name);
    await dialog.getByRole("button", { name: "Add topic" }).click();
  }

  /** Inline-rename a topic row (slug-cased name) to a new name. */
  async renameTaxonomyTopic(slug: string, next: string): Promise<void> {
    const dialog = this.page.getByRole("dialog", { name: "Manage taxonomy" });
    await dialog.getByRole("button", { name: `Rename ${slug}` }).click();
    const input = dialog.getByRole("textbox", { name: `Rename ${slug}` });
    await input.fill(next);
    await dialog.getByRole("button", { name: `Save ${slug}` }).click();
  }

  /** A topic row in the manager located by its display label. */
  taxonomyRow(label: string): Locator {
    return this.page
      .getByRole("dialog", { name: "Manage taxonomy" })
      .getByText(label, { exact: true });
  }

  async closeTaxonomyManager(): Promise<void> {
    await this.page
      .getByRole("dialog", { name: "Manage taxonomy" })
      .getByRole("button", { name: "Close" })
      .click();
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
