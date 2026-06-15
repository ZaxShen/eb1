import { useMemo } from "react";
import type { SegmentDetail, TaxonomyEntry } from "../api";

interface AnnotationPanelProps {
  detail: SegmentDetail | null;
  taxonomy: TaxonomyEntry[];
  topic: string;
  subtopic: string;
  reviewedBy: string;
  saving: boolean;
  onTopicChange: (topic: string) => void;
  onSubtopicChange: (subtopic: string) => void;
  onReviewedByChange: (value: string) => void;
  onSave: () => void;
  onConfirmAi: () => void;
}

export default function AnnotationPanel({
  detail,
  taxonomy,
  topic,
  subtopic,
  reviewedBy,
  saving,
  onTopicChange,
  onSubtopicChange,
  onReviewedByChange,
  onSave,
  onConfirmAi,
}: AnnotationPanelProps) {
  const topics = useMemo(() => {
    const seen = new Set<string>();
    for (const entry of taxonomy) {
      if (entry.topic) seen.add(entry.topic);
    }
    return [...seen].sort();
  }, [taxonomy]);

  const subtopics = useMemo(() => {
    const seen = new Set<string>();
    for (const entry of taxonomy) {
      if (entry.topic === topic && entry.subtopic) seen.add(entry.subtopic);
    }
    return [...seen].sort();
  }, [taxonomy, topic]);

  if (!detail) {
    return (
      <div className="p-4 text-sm text-slate-400">
        Select a segment to annotate.
      </div>
    );
  }

  const seg = detail.segment;
  const canSave = topic.trim() !== "" && subtopic.trim() !== "";

  return (
    <div className="flex h-full flex-col overflow-y-auto p-4">
      <div className="mb-4">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Segment #{seg.id}
        </div>
        <div className="mt-1 text-sm text-slate-600">{seg.conversation}</div>
        {seg.summary && (
          <p className="mt-2 text-sm text-slate-500">{seg.summary}</p>
        )}
      </div>

      <div className="mb-3 rounded border border-slate-200 bg-slate-50 p-2 text-xs text-slate-500">
        AI label: <span className="font-medium">{seg.topic ?? "—"}</span> /{" "}
        <span className="font-medium">{seg.subtopic ?? "—"}</span>
        {seg.label_confidence != null && (
          <span> (conf {seg.label_confidence.toFixed(2)})</span>
        )}
      </div>

      <label className="mb-1 text-xs font-medium text-slate-600">Topic</label>
      <select
        className="mb-3 rounded border border-slate-300 px-2 py-1 text-sm"
        value={topic}
        onChange={(e) => onTopicChange(e.target.value)}
      >
        <option value="">— select topic —</option>
        {topics.map((t) => (
          <option key={t} value={t}>
            {t}
          </option>
        ))}
      </select>

      <label className="mb-1 text-xs font-medium text-slate-600">
        Subtopic
      </label>
      <select
        className="mb-3 rounded border border-slate-300 px-2 py-1 text-sm disabled:bg-slate-100"
        value={subtopic}
        disabled={topic === ""}
        onChange={(e) => onSubtopicChange(e.target.value)}
      >
        <option value="">— select subtopic —</option>
        {subtopics.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>

      <label className="mb-1 text-xs font-medium text-slate-600">
        Reviewer name (optional)
      </label>
      <input
        type="text"
        className="mb-4 rounded border border-slate-300 px-2 py-1 text-sm"
        placeholder="your name"
        value={reviewedBy}
        onChange={(e) => onReviewedByChange(e.target.value)}
      />

      <div className="mt-auto flex flex-col gap-2 pt-2">
        <button
          type="button"
          onClick={onConfirmAi}
          className="rounded border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"
          title="Accept the AI label as gold (Space)"
        >
          Confirm AI label{" "}
          <span className="text-xs text-slate-400">(Space)</span>
        </button>
        <button
          type="button"
          onClick={onSave}
          disabled={!canSave || saving}
          className="rounded bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-slate-300"
          title="Save the corrected label (Enter)"
        >
          {saving ? "Saving…" : "Save"}{" "}
          <span className="text-xs text-blue-200">(Enter)</span>
        </button>
        <p className="text-center text-xs text-slate-400">
          ← / → to move between segments
        </p>
      </div>
    </div>
  );
}
