import type { SegmentFilters, Stats } from "../api";
import type { TaxonomyMap } from "../lib/taxonomy";
import { Badge } from "@/components/ui/badge";
import { cn, formatLabel } from "../lib/utils";
import { topicBarClass } from "../lib/badges";

interface StatisticsPanelProps {
  stats: Stats | null;
  filters: SegmentFilters;
  taxonomy: TaxonomyMap;
  onFiltersChange: (filters: SegmentFilters) => void;
}

const StatisticsPanel = ({
  stats,
  filters,
  taxonomy,
  onFiltersChange,
}: StatisticsPanelProps) => {
  const topicEntries = Object.entries(stats?.per_topic ?? {}).sort(
    (a, b) => b[1] - a[1],
  );
  const maxTopicCount = topicEntries.reduce((m, [, c]) => Math.max(m, c), 0) || 1;

  return (
    <div className="flex flex-col gap-2.5 p-3">
      <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        Statistics
      </h3>

      <div className="flex flex-wrap items-center gap-1.5">
        <Badge
          variant="secondary"
          title="Show all segments"
          onClick={() => onFiltersChange({ ...filters, status: undefined })}
          className={cn(
            "cursor-pointer",
            !filters.status && "ring-1 ring-primary",
          )}
        >
          {stats?.total ?? 0} total
        </Badge>
        <Badge
          variant="secondary"
          title="Filter reviewed segments"
          onClick={() =>
            onFiltersChange({
              ...filters,
              status: filters.status === "reviewed" ? undefined : "reviewed",
            })
          }
          className={cn(
            "cursor-pointer",
            filters.status === "reviewed" && "ring-1 ring-primary",
          )}
        >
          <span className="size-1.5 rounded-full bg-positive" />
          {stats?.reviewed ?? 0} reviewed
        </Badge>
        <Badge
          variant="secondary"
          title="Filter segments pending review"
          onClick={() =>
            onFiltersChange({
              ...filters,
              status:
                filters.status === "unreviewed" ? undefined : "unreviewed",
            })
          }
          className={cn(
            "cursor-pointer",
            filters.status === "unreviewed" && "ring-1 ring-primary",
          )}
        >
          <span className="size-1.5 rounded-full bg-neutral-mixed" />
          {stats?.unreviewed ?? 0} unreviewed
        </Badge>
      </div>

      {topicEntries.length > 0 && (
        <div className="flex flex-col gap-1 pt-1">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Per topic
          </span>
          {topicEntries.map(([topic, count]) => {
            const active = filters.topic === topic;
            return (
              <button
                key={topic}
                onClick={() =>
                  onFiltersChange({
                    ...filters,
                    topic: active ? undefined : topic,
                  })
                }
                className={cn(
                  "flex items-center gap-2 rounded-md px-1 py-0.5 transition-colors hover:bg-accent",
                  active && "bg-accent",
                )}
                title={`Filter by ${formatLabel(topic)}`}
              >
                <span className="w-28 shrink-0 truncate text-left text-[11px]">
                  {taxonomy[topic]?.name ?? formatLabel(topic)}
                </span>
                <span className="relative h-2 flex-1 overflow-hidden rounded-full bg-muted">
                  <span
                    className={cn(
                      "absolute inset-y-0 left-0 rounded-full",
                      topicBarClass(topic),
                    )}
                    style={{ width: `${(count / maxTopicCount) * 100}%` }}
                  />
                </span>
                <span className="w-7 shrink-0 text-right text-[11px] tabular-nums text-muted-foreground">
                  {count}
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default StatisticsPanel;
