import { useCallback, useState } from "react";

// In-memory undo/redo for annotation mutations (single-operator, cleared on
// reload). Each entry captures before/after state as closures: `undo` re-applies
// the before-state, `redo` re-applies the after-state. Performing a new action
// (push) clears the redo stack.
export interface HistoryEntry {
  label: string;
  undo: () => Promise<void>;
  redo: () => Promise<void>;
}

export interface History {
  canUndo: boolean;
  canRedo: boolean;
  push: (entry: HistoryEntry) => void;
  undo: () => Promise<void>;
  redo: () => Promise<void>;
}

export function useHistory(): History {
  const [undoStack, setUndoStack] = useState<HistoryEntry[]>([]);
  const [redoStack, setRedoStack] = useState<HistoryEntry[]>([]);

  const push = useCallback((entry: HistoryEntry) => {
    setUndoStack((stack) => [...stack, entry]);
    setRedoStack([]);
  }, []);

  const undo = useCallback(async () => {
    const entry = undoStack[undoStack.length - 1];
    if (!entry) return;
    await entry.undo();
    setUndoStack((stack) => stack.slice(0, -1));
    setRedoStack((stack) => [...stack, entry]);
  }, [undoStack]);

  const redo = useCallback(async () => {
    const entry = redoStack[redoStack.length - 1];
    if (!entry) return;
    await entry.redo();
    setRedoStack((stack) => stack.slice(0, -1));
    setUndoStack((stack) => [...stack, entry]);
  }, [redoStack]);

  return {
    canUndo: undoStack.length > 0,
    canRedo: redoStack.length > 0,
    push,
    undo,
    redo,
  };
}
