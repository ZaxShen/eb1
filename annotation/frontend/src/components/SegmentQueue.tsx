import type { SegmentFilters, SegmentSummary } from "../api";
import type { TaxonomyMap } from "../lib/taxonomy";
import { sortedTopics } from "../lib/taxonomy";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";
import {
  sentimentBadgeClass,
  SUBTOPIC_BADGE_CLASS,
  topicColorClass,
  topicTextColor,
} from "../lib/badges";
import { cn, formatConfidence, formatLabel } from "../lib/utils";
import { RotateCcw, Tag, User } from "./icons";

interface SegmentQueueProps {
  segments: SegmentSummary[];
  selectedId: number | null;
  filters: SegmentFilters;
  taxonomy: TaxonomyMap;
  loading: boolean;
  total: number;
  onSelect: (segmentId: number) => void;
  onFiltersChange: (filters: SegmentFilters) => void;
}

const SegmentCard = ({
  segment,
  isSelected,
  onClick,
}: {
  segment: SegmentSummary;
  isSelected: boolean;
  onClick: () => void;
}) => (
  <button
    onClick={onClick}
    className={cn(
      "w-full text-left rounded-lg px-2 py-3 border transition-colors hover:bg-secondary/70 focus:outline-none",
      isSelected ? "bg-secondary border-border" : "border-transparent",
    )}
  >
    <div className="flex items-center gap-2 mb-1.5">
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-secondary text-muted-foreground">
        <User className="h-3.5 w-3.5" />
      </span>
      <span className="text-sm font-medium truncate flex-1">
        {segment.conversation}
      </span>
      {segment.reviewed && (
        <span className="inline-block w-2 h-2 rounded-full bg-green-500 shrink-0" />
      )}
    </div>

    <div className="flex items-center gap-1 flex-wrap mb-1">
      {segment.topic ? (
        <Badge variant="secondary" className={cn("border", topicColorClass(segment.topic))}>
          {formatLabel(segment.topic)}
        </Badge>
      ) : (
        <Badge variant="outline" className="text-muted-foreground">
          No topic
        </Badge>
      )}
      {segment.subtopic && (
        <Badge variant="outline" className={SUBTOPIC_BADGE_CLASS}>
          {formatLabel(segment.subtopic)}
        </Badge>
      )}
      {segment.sentiment && (
        <Badge variant="outline" className={cn("border", sentimentBadgeClass(segment.sentiment))}>
          {segment.sentiment}
        </Badge>
      )}
    </div>

    <p className="text-xs text-muted-foreground line-clamp-2 leading-relaxed">
      {segment.summary ?? "No summary available"}
    </p>

    <div className="mt-1 flex items-center gap-2 flex-wrap">
      <span className="text-xs text-muted-foreground">
        Confidence:{" "}
        <span className="text-foreground">{formatConfidence(segment.label_confidence)}</span>
      </span>
      <span className="text-xs text-muted-foreground">chunk {segment.chunk_index}</span>
    </div>
  </button>
);

const SegmentQueue = ({
  segments,
  selectedId,
  filters,
  taxonomy,
  loading,
  total,
  onSelect,
  onFiltersChange,
}: SegmentQueueProps) => {
  const topics = sortedTopics(taxonomy);
  const update = (patch: Partial<SegmentFilters>) =>
    onFiltersChange({ ...filters, ...patch });

  const hasActiveFilters =
    filters.status !== undefined ||
    filters.topic !== undefined ||
    filters.max_confidence !== undefined;

  const maxConfidencePct =
    filters.max_confidence !== undefined ? Math.round(filters.max_confidence * 100) : 100;

  const statusOptions: { value: SegmentFilters["status"]; label: string }[] = [
    { value: undefined, label: "All" },
    { value: "unreviewed", label: "Unreviewed" },
    { value: "reviewed", label: "Reviewed" },
  ];

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="flex flex-col gap-2 p-3 border-b border-border/50">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-bold">Topic Annotation</h2>
          {hasActiveFilters && (
            <Button
              variant="ghost"
              size="icon"
              onClick={() => onFiltersChange({})}
              title="Reset all filters"
            >
              <RotateCcw className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>

        <div className="flex items-center gap-1">
          {statusOptions.map((opt) => (
            <button
              key={opt.label}
              onClick={() => update({ status: opt.value })}
              className={cn(
                "flex-1 rounded-md px-2 py-1 text-xs font-medium transition-colors",
                filters.status === opt.value
                  ? "bg-primary text-primary-foreground"
                  : "bg-secondary/60 text-secondary-foreground hover:bg-secondary",
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-1.5 rounded-md border border-border bg-background px-2">
          <Tag className="h-3 w-3 text-muted-foreground shrink-0" />
          <select
            value={filters.topic ?? "__all__"}
            onChange={(e) =>
              update({ topic: e.target.value === "__all__" ? undefined : e.target.value })
            }
            className="flex-1 bg-transparent py-1.5 text-xs focus:outline-none"
          >
            <option value="__all__">All topics</option>
            {topics.map((t) => (
              <option key={t} value={t} className={topicTextColor(t)}>
                {taxonomy[t]?.name ?? formatLabel(t)}
              </option>
            ))}
          </select>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground shrink-0">
            Max conf
          </span>
          <input
            type="range"
            min={0}
            max={100}
            step={5}
            value={maxConfidencePct}
            onChange={(e) => {
              const pct = Number(e.target.value);
              update({ max_confidence: pct >= 100 ? undefined : pct / 100 });
            }}
            className="flex-1 accent-[hsl(var(--primary))]"
          />
          <span className="text-xs tabular-nums w-10 text-right text-muted-foreground">
            {filters.max_confidence !== undefined ? `${maxConfidencePct}%` : "off"}
          </span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-2 py-2">
        {loading && (
          <div className="flex items-center justify-center h-32 text-sm text-muted-foreground">
            Loading…
          </div>
        )}
        {!loading && segments.length === 0 && (
          <div className="flex items-center justify-center h-32 text-sm text-muted-foreground">
            No segments found
          </div>
        )}
        {!loading && segments.length > 0 && (
          <div className="flex flex-col gap-1">
            {segments.map((segment) => (
              <SegmentCard
                key={segment.id}
                segment={segment}
                isSelected={selectedId === segment.id}
                onClick={() => onSelect(segment.id)}
              />
            ))}
          </div>
        )}
      </div>

      <div className="border-t border-border/50 px-4 py-1.5 text-center text-xs text-muted-foreground">
        {segments.length} shown · {total} total segment{total !== 1 ? "s" : ""}
      </div>
    </div>
  );
};

export default SegmentQueue;
