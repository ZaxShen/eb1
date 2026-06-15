// Pure span-set math for boundary edits, extracted from ConversationStream so
// it can be tested in isolation. A "span" is a segment's ordered list of
// message indices; `spans` is the ordered list of those arrays. Both
// operations return a NEW ordered span set (the input is never mutated) and
// preserve the union of all indices.

export type Span = number[];

/**
 * Split the span at `segmentIndex` into two at `messageIndex`: indices below
 * `messageIndex` stay in the first span, indices at or above start a new span.
 * A side that would be empty is dropped (an empty-producing split is a no-op
 * for that side). Returns the new ordered span set.
 */
export function splitAt(
  spans: Span[],
  segmentIndex: number,
  messageIndex: number,
): Span[] {
  const result: Span[] = [];
  for (let i = 0; i < spans.length; i += 1) {
    if (i !== segmentIndex) {
      result.push(spans[i]);
      continue;
    }
    const before = spans[i].filter((idx) => idx < messageIndex);
    const after = spans[i].filter((idx) => idx >= messageIndex);
    if (before.length > 0) result.push(before);
    if (after.length > 0) result.push(after);
  }
  return result;
}

/**
 * Merge the span at `segmentIndex` into the immediately-previous span,
 * producing the sorted union of their indices. Merging the first segment
 * (`segmentIndex <= 0`) is a no-op (returns the spans unchanged).
 */
export function mergeWithPrevious(spans: Span[], segmentIndex: number): Span[] {
  if (segmentIndex <= 0 || segmentIndex >= spans.length) return spans;
  const result: Span[] = [];
  for (let i = 0; i < spans.length; i += 1) {
    if (i === segmentIndex) continue;
    if (i === segmentIndex - 1) {
      result.push(
        [...spans[i], ...spans[segmentIndex]].sort((a, b) => a - b),
      );
    } else {
      result.push(spans[i]);
    }
  }
  return result;
}
