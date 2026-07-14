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

/**
 * True when every message in a conversation carries the SAME timestamp — the
 * signature of a synthetic ingest (SuperDialseg fabricates one uniform time for
 * a whole dialogue). Callers suppress per-message time captions when this holds;
 * real corpora with varying timestamps return false and are unaffected.
 */
export function hasUniformTimestamps(
  timestamps: (string | null | undefined)[],
): boolean {
  const present = timestamps.filter((t): t is string => Boolean(t));
  if (present.length === 0) return false;
  return present.every((t) => t === present[0]);
}

/** True when two ISO timestamps fall within the same minute. */
export function isSameMinute(
  a: string | null | undefined,
  b: string | null | undefined,
): boolean {
  if (!a || !b) return false;
  return a.slice(0, 16) === b.slice(0, 16);
}
