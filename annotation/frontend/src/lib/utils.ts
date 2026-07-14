import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** Convert a slug to a display name (Title Case, underscores → spaces). */
export function formatLabel(slug: string | null | undefined): string {
  if (typeof slug !== "string" || !slug) return "—";
  return slug.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function formatConfidence(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${Math.round(value * 100)}%`;
}

/** Smart timestamp: time-only for today, "Mon D, HH:mm" otherwise. */
export function formatChatTimestamp(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const now = new Date();
  const sameDay =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate();
  const time = date.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
  if (sameDay) return time;
  const day = date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
  return `${day}, ${time}`;
}

const SYNTHETIC_TIMESTAMP_EPOCH = Date.UTC(2000, 0, 1);

/**
 * True when a conversation's timestamps are fabricated by a synthetic ingest,
 * so callers can suppress per-message time captions. Fires when EITHER every
 * present timestamp is identical (SuperDialseg's uniform-time ingest) OR every
 * present timestamp predates 2000-01-01 (its epoch-era `1970-01-01 + Ns`
 * sequential fabrication). No real chat corpus predates 2000, so corpora with
 * genuine varying timestamps return false and are unaffected.
 */
export function hasSyntheticTimestamps(
  timestamps: (string | null | undefined)[],
): boolean {
  const present = timestamps.filter((t): t is string => Boolean(t));
  if (present.length === 0) return false;
  if (present.every((t) => t === present[0])) return true;
  return present.every((t) => {
    const ms = new Date(t).getTime();
    return !Number.isNaN(ms) && ms < SYNTHETIC_TIMESTAMP_EPOCH;
  });
}

/** True when two ISO timestamps fall within the same minute. */
export function isSameMinute(
  a: string | null | undefined,
  b: string | null | undefined,
): boolean {
  if (!a || !b) return false;
  return a.slice(0, 16) === b.slice(0, 16);
}
