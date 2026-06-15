// Topic/sentiment color helpers. The backend taxonomy has no source field, so a
// topic is colored deterministically by hashing its slug into a fixed palette —
// stable across renders, distinct per topic. All classes use semantic theme
// tokens (chart-* / role / sentiment), never raw Tailwind color scales.

const TOPIC_PALETTE = [
  "bg-chart-1/15 text-chart-1 border-chart-1/30",
  "bg-chart-2/15 text-chart-2 border-chart-2/30",
  "bg-chart-3/15 text-chart-3 border-chart-3/30",
  "bg-chart-4/15 text-chart-4 border-chart-4/30",
  "bg-chart-5/15 text-chart-5 border-chart-5/30",
];

const TOPIC_BAR_PALETTE = [
  "bg-chart-1",
  "bg-chart-2",
  "bg-chart-3",
  "bg-chart-4",
  "bg-chart-5",
];

function hashIndex(slug: string, modulo: number): number {
  let hash = 0;
  for (let i = 0; i < slug.length; i += 1) {
    hash = (hash * 31 + slug.charCodeAt(i)) | 0;
  }
  return Math.abs(hash) % modulo;
}

/** Topic badge color class — deterministic from the topic slug. */
export function topicColorClass(topic: string | null | undefined): string {
  if (!topic) return "";
  return TOPIC_PALETTE[hashIndex(topic, TOPIC_PALETTE.length)];
}

/** Solid topic color for stat mini-bars. */
export function topicBarClass(topic: string | null | undefined): string {
  if (!topic) return "bg-muted-foreground";
  return TOPIC_BAR_PALETTE[hashIndex(topic, TOPIC_BAR_PALETTE.length)];
}

/** Sentiment badge color class, using semantic sentiment tokens. */
export function sentimentBadgeClass(sentiment: string | null | undefined): string {
  switch (sentiment) {
    case "positive":
      return "bg-positive/15 text-positive border-positive/30";
    case "negative":
      return "bg-negative/15 text-negative border-negative/30";
    case "mixed":
      return "bg-neutral-mixed/15 text-neutral-mixed border-neutral-mixed/30";
    default:
      return "bg-secondary text-secondary-foreground border-transparent";
  }
}

export const SUBTOPIC_BADGE_CLASS =
  "bg-accent text-accent-foreground border-border";
