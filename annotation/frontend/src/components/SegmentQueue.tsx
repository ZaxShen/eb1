import { RotateCcw, Tag, User } from "lucide-react";
import type { SegmentFilters, SegmentSummary } from "../api";
import type { TaxonomyMap } from "../lib/taxonomy";
import { sortedTopics } from "../lib/taxonomy";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Slider } from "@/components/ui/slider";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  sentimentBadgeClass,
  SUBTOPIC_BADGE_CLASS,
  topicColorClass,
} from "../lib/badges";
import { cn, formatConfidence, formatLabel } from "../lib/utils";

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

const ALL_TOPICS = "__all__";

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
      "w-full rounded-lg border px-2.5 py-3 text-left transition-colors hover:bg-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-ring",
      isSelected
        ? "border-primary/40 bg-accent ring-1 ring-primary/30"
        : "border-transparent",
    )}
  >
    <div className="mb-1.5 flex items-center gap-2">
      <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-secondary text-muted-foreground">
        <User className="size-3.5" />
      </span>
      <span className="flex-1 truncate text-sm font-medium">
        {segment.conversation}
      </span>
      {segment.reviewed && (
        <span className="size-2 shrink-0 rounded-full bg-positive" />
      )}
    </div>

    <div className="mb-1 flex flex-wrap items-center gap-1">
      {segment.topic ? (
        <Badge variant="outline" className={topicColorClass(segment.topic)}>
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
        <Badge
          variant="outline"
          className={sentimentBadgeClass(segment.sentiment)}
        >
          {segment.sentiment}
        </Badge>
      )}
    </div>

    <p className="line-clamp-2 text-xs leading-relaxed text-muted-foreground">
      {segment.summary ?? "No summary available"}
    </p>

    <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
      <span>
        Confidence{" "}
        <span className="text-foreground">
          {formatConfidence(segment.label_confidence)}
        </span>
      </span>
      <span>chunk {segment.chunk_index}</span>
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
    filters.max_confidence !== undefined
      ? Math.round(filters.max_confidence * 100)
      : 100;

  const statusOptions: { value: SegmentFilters["status"]; label: string }[] = [
    { value: undefined, label: "All" },
    { value: "unreviewed", label: "Unreviewed" },
    { value: "reviewed", label: "Reviewed" },
  ];

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex flex-col gap-2.5 p-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold tracking-tight">
            Topic Annotation
          </h2>
          {hasActiveFilters && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  onClick={() => onFiltersChange({})}
                >
                  <RotateCcw />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Reset all filters</TooltipContent>
            </Tooltip>
          )}
        </div>

        <div className="flex items-center gap-1 rounded-md bg-muted p-0.5">
          {statusOptions.map((opt) => (
            <button
              key={opt.label}
              onClick={() => update({ status: opt.value })}
              className={cn(
                "flex-1 rounded-sm px-2 py-1 text-xs font-medium transition-colors",
                filters.status === opt.value
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>

        <Select
          value={filters.topic ?? ALL_TOPICS}
          onValueChange={(v) =>
            update({ topic: v === ALL_TOPICS ? undefined : v })
          }
        >
          <SelectTrigger size="sm" className="w-full">
            <Tag className="size-3.5 text-muted-foreground" />
            <SelectValue placeholder="All topics" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_TOPICS}>All topics</SelectItem>
            {topics.map((t) => (
              <SelectItem key={t} value={t}>
                {taxonomy[t]?.name ?? formatLabel(t)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <div className="flex flex-col gap-1.5">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Max confidence
            </span>
            <span className="text-xs tabular-nums text-muted-foreground">
              {filters.max_confidence !== undefined
                ? `${maxConfidencePct}%`
                : "off"}
            </span>
          </div>
          <Slider
            min={0}
            max={100}
            step={5}
            value={[maxConfidencePct]}
            onValueChange={([pct]) =>
              update({ max_confidence: pct >= 100 ? undefined : pct / 100 })
            }
          />
        </div>
      </div>

      <Separator />

      <ScrollArea className="min-h-0 flex-1">
        <div className="p-2">
          {loading && (
            <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
              Loading…
            </div>
          )}
          {!loading && segments.length === 0 && (
            <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
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
      </ScrollArea>

      <Separator />
      <div className="px-4 py-1.5 text-center text-xs text-muted-foreground">
        {segments.length} shown · {total} total segment{total !== 1 ? "s" : ""}
      </div>
    </div>
  );
};

export default SegmentQueue;
