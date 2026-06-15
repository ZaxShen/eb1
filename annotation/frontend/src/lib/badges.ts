// Badge color helpers, porting the idea from ufl-dev's TopicAnnotation/utils.ts.
// ufl colors topics by taxonomy source (user → cyan, bot → purple); our backend
// taxonomy has no source field, so we color a topic deterministically by hashing
// its slug into a fixed palette — stable across renders, distinct per topic.

const TOPIC_PALETTE = [
  "bg-cyan-500/20 text-cyan-600 dark:text-cyan-400 border-cyan-500/30",
  "bg-purple-500/20 text-purple-600 dark:text-purple-400 border-purple-500/30",
  "bg-sky-500/20 text-sky-600 dark:text-sky-400 border-sky-500/30",
  "bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 border-emerald-500/30",
  "bg-rose-500/20 text-rose-600 dark:text-rose-400 border-rose-500/30",
  "bg-indigo-500/20 text-indigo-600 dark:text-indigo-400 border-indigo-500/30",
  "bg-teal-500/20 text-teal-600 dark:text-teal-400 border-teal-500/30",
  "bg-fuchsia-500/20 text-fuchsia-600 dark:text-fuchsia-400 border-fuchsia-500/30",
];

const TOPIC_TEXT_PALETTE = [
  "text-cyan-600 dark:text-cyan-400",
  "text-purple-600 dark:text-purple-400",
  "text-sky-600 dark:text-sky-400",
  "text-emerald-600 dark:text-emerald-400",
  "text-rose-600 dark:text-rose-400",
  "text-indigo-600 dark:text-indigo-400",
  "text-teal-600 dark:text-teal-400",
  "text-fuchsia-600 dark:text-fuchsia-400",
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

/** Text-only color for topic dropdown items. */
export function topicTextColor(topic: string | null | undefined): string {
  if (!topic) return "";
  return TOPIC_TEXT_PALETTE[hashIndex(topic, TOPIC_TEXT_PALETTE.length)];
}

/** Sentiment badge color class (ported verbatim from ufl utils.ts). */
export function sentimentBadgeClass(sentiment: string | null | undefined): string {
  switch (sentiment) {
    case "positive":
      return "bg-green-500/20 text-green-600 dark:text-green-400 border-green-500/30";
    case "negative":
      return "bg-red-500/20 text-red-600 dark:text-red-400 border-red-500/30";
    case "mixed":
      return "bg-orange-500/20 text-orange-600 dark:text-orange-400 border-orange-500/30";
    default:
      return "bg-secondary text-secondary-foreground border-transparent";
  }
}

export const SUBTOPIC_BADGE_CLASS =
  "bg-yellow-500/20 text-yellow-700 dark:text-yellow-400 border-yellow-500/30";
