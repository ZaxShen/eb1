import type { TaxonomyEntry } from "../api";
import { formatLabel } from "./utils";

export interface TaxonomyTopic {
  name: string;
  subtopics: string[];
}

/** Nested topic → subtopics map, built from the flat /taxonomy list. */
export type TaxonomyMap = Record<string, TaxonomyTopic>;

export function buildTaxonomyMap(entries: TaxonomyEntry[]): TaxonomyMap {
  const map: TaxonomyMap = {};
  for (const entry of entries) {
    if (!entry.topic) continue;
    const topic = (map[entry.topic] ??= {
      name: formatLabel(entry.topic),
      subtopics: [],
    });
    if (entry.subtopic && !topic.subtopics.includes(entry.subtopic)) {
      topic.subtopics.push(entry.subtopic);
    }
  }
  for (const topic of Object.values(map)) {
    topic.subtopics.sort((a, b) => a.localeCompare(b));
  }
  return map;
}

export function sortedTopics(map: TaxonomyMap): string[] {
  return Object.keys(map).sort((a, b) => a.localeCompare(b));
}

export function subtopicsFor(
  map: TaxonomyMap,
  topic: string | undefined | null,
): string[] {
  if (!topic) return [];
  return map[topic]?.subtopics ?? [];
}
