import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useHistory, type HistoryEntry } from "./useHistory";

function makeEntry(label: string): HistoryEntry & {
  undo: ReturnType<typeof vi.fn>;
  redo: ReturnType<typeof vi.fn>;
} {
  return {
    label,
    undo: vi.fn().mockResolvedValue(undefined),
    redo: vi.fn().mockResolvedValue(undefined),
  };
}

describe("useHistory", () => {
  it("starts empty: canUndo and canRedo are false", () => {
    const { result } = renderHook(() => useHistory());
    expect(result.current.canUndo).toBe(false);
    expect(result.current.canRedo).toBe(false);
  });

  it("push appends to the undo stack and clears the redo stack", async () => {
    const { result } = renderHook(() => useHistory());
    const a = makeEntry("a");

    act(() => result.current.push(a));
    expect(result.current.canUndo).toBe(true);
    expect(result.current.canRedo).toBe(false);

    await act(async () => {
      await result.current.undo();
    });
    expect(result.current.canRedo).toBe(true);

    // A fresh push must clear the redo stack.
    act(() => result.current.push(makeEntry("b")));
    expect(result.current.canRedo).toBe(false);
    expect(result.current.canUndo).toBe(true);
  });

  it("undo awaits entry.undo and moves the entry to the redo stack", async () => {
    const { result } = renderHook(() => useHistory());
    const a = makeEntry("a");
    act(() => result.current.push(a));

    await act(async () => {
      await result.current.undo();
    });

    expect(a.undo).toHaveBeenCalledTimes(1);
    expect(a.redo).not.toHaveBeenCalled();
    expect(result.current.canUndo).toBe(false);
    expect(result.current.canRedo).toBe(true);
  });

  it("redo awaits entry.redo and moves the entry back to the undo stack", async () => {
    const { result } = renderHook(() => useHistory());
    const a = makeEntry("a");
    act(() => result.current.push(a));
    await act(async () => {
      await result.current.undo();
    });

    await act(async () => {
      await result.current.redo();
    });

    expect(a.redo).toHaveBeenCalledTimes(1);
    expect(result.current.canUndo).toBe(true);
    expect(result.current.canRedo).toBe(false);
  });

  it("undo on an empty stack is a no-op and does not throw", async () => {
    const { result } = renderHook(() => useHistory());
    await act(async () => {
      await result.current.undo();
      await result.current.redo();
    });
    expect(result.current.canUndo).toBe(false);
    expect(result.current.canRedo).toBe(false);
  });

  it("a push/undo/redo/undo sequence ends with the entry redoable again", async () => {
    const { result } = renderHook(() => useHistory());
    const a = makeEntry("a");

    act(() => result.current.push(a));
    await act(async () => {
      await result.current.undo();
    });
    await act(async () => {
      await result.current.redo();
    });
    await act(async () => {
      await result.current.undo();
    });

    expect(a.undo).toHaveBeenCalledTimes(2);
    expect(a.redo).toHaveBeenCalledTimes(1);
    expect(result.current.canUndo).toBe(false);
    expect(result.current.canRedo).toBe(true);
  });
});
