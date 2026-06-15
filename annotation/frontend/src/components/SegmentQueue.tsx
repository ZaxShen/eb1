import type { SegmentFilters, SegmentSummary } from "../api";

interface SegmentQueueProps {
  segments: SegmentSummary[];
  selectedId: number | null;
  filters: SegmentFilters;
  topics: string[];
  loading: boolean;
  onSelect: (segmentId: number) => void;
  onFiltersChange: (filters: SegmentFilters) => void;
}

export default function SegmentQueue({
  segments,
  selectedId,
  filters,
  topics,
  loading,
  onSelect,
  onFiltersChange,
}: SegmentQueueProps) {
  return (
    <div className="flex h-full flex-col">
      <div className="space-y-2 border-b border-slate-200 p-3">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Queue ({segments.length})
        </div>
        <select
          className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
          value={filters.status ?? ""}
          onChange={(e) =>
            onFiltersChange({
              ...filters,
              status: (e.target.value || undefined) as SegmentFilters["status"],
            })
          }
        >
          <option value="">All statuses</option>
          <option value="unreviewed">Unreviewed</option>
          <option value="reviewed">Reviewed</option>
        </select>
        <select
          className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
          value={filters.topic ?? ""}
          onChange={(e) =>
            onFiltersChange({
              ...filters,
              topic: e.target.value || undefined,
            })
          }
        >
          <option value="">All topics</option>
          {topics.map((topic) => (
            <option key={topic} value={topic}>
              {topic}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-2 text-sm text-slate-600">
          <span className="whitespace-nowrap">Max conf.</span>
          <input
            type="number"
            min={0}
            max={1}
            step={0.05}
            className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
            value={filters.max_confidence ?? ""}
            onChange={(e) =>
              onFiltersChange({
                ...filters,
                max_confidence:
                  e.target.value === ""
                    ? undefined
                    : Number(e.target.value),
              })
            }
          />
        </label>
      </div>

      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="p-3 text-sm text-slate-400">Loading…</div>
        ) : segments.length === 0 ? (
          <div className="p-3 text-sm text-slate-400">No segments.</div>
        ) : (
          <ul>
            {segments.map((seg) => {
              const active = seg.id === selectedId;
              return (
                <li key={seg.id}>
                  <button
                    type="button"
                    onClick={() => onSelect(seg.id)}
                    className={`flex w-full flex-col items-start gap-1 border-b border-slate-100 px-3 py-2 text-left text-sm hover:bg-slate-50 ${
                      active ? "bg-blue-50" : ""
                    }`}
                  >
                    <div className="flex w-full items-center justify-between gap-2">
                      <span className="font-medium text-slate-800">
                        {seg.topic ?? "—"}
                      </span>
                      <span
                        className={`rounded px-1.5 py-0.5 text-xs ${
                          seg.reviewed
                            ? "bg-green-100 text-green-700"
                            : "bg-amber-100 text-amber-700"
                        }`}
                      >
                        {seg.reviewed ? "reviewed" : "new"}
                      </span>
                    </div>
                    <div className="text-xs text-slate-500">
                      {seg.subtopic ?? "—"}
                      {seg.label_confidence != null && (
                        <span className="ml-2">
                          conf {seg.label_confidence.toFixed(2)}
                        </span>
                      )}
                    </div>
                    <div className="line-clamp-2 text-xs text-slate-400">
                      {seg.summary ?? seg.conversation}
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
