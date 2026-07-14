import { describe, expect, it } from "vitest";
import { hasSyntheticTimestamps, slugify } from "./utils";

// Parity cases: these MUST match the Python `slugify` tests in
// tests/test_annotation_taxonomy.py so the live preview equals what the backend
// stores. Keep the two lists identical.
const SLUG_CASES: [string, string][] = [
  ["Veterans  Affairs!", "veterans_affairs"],
  ["Billing", "billing"],
  ["cover_letter", "cover_letter"],
  ["  spaced  out  ", "spaced_out"],
  ["R&D / ops", "r_d_ops"],
  ["Multi--Dash__Score", "multi_dash_score"],
];

describe("slugify", () => {
  it.each(SLUG_CASES)("normalizes %j → %j", (input, expected) => {
    expect(slugify(input)).toBe(expected);
  });

  it("returns an empty string for blank / punctuation-only input", () => {
    expect(slugify("")).toBe("");
    expect(slugify("   ")).toBe("");
    expect(slugify("!!!")).toBe("");
  });
});

describe("hasSyntheticTimestamps", () => {
  it("treats epoch-era sequential timestamps as synthetic", () => {
    const epoch = Array.from({ length: 4 }, (_, i) =>
      new Date(i * 1000).toISOString(),
    );
    expect(hasSyntheticTimestamps(epoch)).toBe(true);
  });

  it("treats all-identical timestamps as synthetic", () => {
    const uniform = "2020-01-01T00:00:00Z";
    expect(hasSyntheticTimestamps([uniform, uniform, uniform])).toBe(true);
  });

  it("leaves realistic varying timestamps alone", () => {
    expect(
      hasSyntheticTimestamps([
        "2024-05-01T10:00:00Z",
        "2024-05-01T10:00:30Z",
        "2024-05-01T10:05:00Z",
      ]),
    ).toBe(false);
  });

  it("returns false when no timestamps are present", () => {
    expect(hasSyntheticTimestamps([null, undefined, ""])).toBe(false);
  });

  it("ignores nulls when the present timestamps are all epoch-era", () => {
    expect(
      hasSyntheticTimestamps([
        null,
        "1970-01-01T00:00:01Z",
        undefined,
        "1970-01-01T00:00:02Z",
      ]),
    ).toBe(true);
  });
});
