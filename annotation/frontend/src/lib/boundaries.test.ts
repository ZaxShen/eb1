import { describe, expect, it } from "vitest";
import { mergeWithPrevious, splitAt, type Span } from "./boundaries";

const union = (spans: Span[]): number[] =>
  spans.flat().sort((a, b) => a - b);

const isSorted = (spans: Span[]): boolean =>
  spans.every((s) => s.every((v, i) => i === 0 || s[i - 1] < v)) &&
  spans.every(
    (s, i) =>
      i === 0 || (spans[i - 1].at(-1) ?? -Infinity) < (s[0] ?? Infinity),
  );

describe("splitAt", () => {
  it("splits a segment into two contiguous spans whose union equals the original", () => {
    const spans: Span[] = [[0, 1, 2, 3]];
    const result = splitAt(spans, 0, 2);
    expect(result).toEqual([
      [0, 1],
      [2, 3],
    ]);
    expect(union(result)).toEqual(union(spans));
  });

  it("leaves other segments untouched and keeps the set sorted + covering all indices", () => {
    const spans: Span[] = [
      [0, 1],
      [2, 3, 4, 5],
      [6, 7],
    ];
    const result = splitAt(spans, 1, 4);
    expect(result).toEqual([
      [0, 1],
      [2, 3],
      [4, 5],
      [6, 7],
    ]);
    expect(union(result)).toEqual([0, 1, 2, 3, 4, 5, 6, 7]);
    expect(isSorted(result)).toBe(true);
  });

  it("rejects an empty-producing split: at the first index, the original span survives unchanged", () => {
    const spans: Span[] = [[2, 3, 4]];
    expect(splitAt(spans, 0, 2)).toEqual([[2, 3, 4]]);
  });

  it("rejects an empty-producing split above the last index (no empty after-span)", () => {
    const spans: Span[] = [[2, 3, 4]];
    expect(splitAt(spans, 0, 5)).toEqual([[2, 3, 4]]);
  });

  it("does not mutate the input span set", () => {
    const spans: Span[] = [[0, 1, 2, 3]];
    const snapshot = structuredClone(spans);
    splitAt(spans, 0, 2);
    expect(spans).toEqual(snapshot);
  });
});

describe("mergeWithPrevious", () => {
  it("merges adjacent segments into one span equal to their union", () => {
    const spans: Span[] = [
      [0, 1],
      [2, 3],
      [4, 5],
    ];
    const result = mergeWithPrevious(spans, 1);
    expect(result).toEqual([
      [0, 1, 2, 3],
      [4, 5],
    ]);
    expect(union(result)).toEqual([0, 1, 2, 3, 4, 5]);
  });

  it("merge of the first segment is a no-op", () => {
    const spans: Span[] = [
      [0, 1],
      [2, 3],
    ];
    expect(mergeWithPrevious(spans, 0)).toBe(spans);
  });

  it("out-of-range index is a no-op", () => {
    const spans: Span[] = [
      [0, 1],
      [2, 3],
    ];
    expect(mergeWithPrevious(spans, 5)).toBe(spans);
  });

  it("produces a sorted union when source indices are interleaved", () => {
    const spans: Span[] = [
      [0, 2, 4],
      [1, 3, 5],
    ];
    expect(mergeWithPrevious(spans, 1)).toEqual([[0, 1, 2, 3, 4, 5]]);
  });

  it("does not mutate the input span set", () => {
    const spans: Span[] = [
      [0, 1],
      [2, 3],
    ];
    const snapshot = structuredClone(spans);
    mergeWithPrevious(spans, 1);
    expect(spans).toEqual(snapshot);
  });
});
