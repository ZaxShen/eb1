import type { SegmentFilters, Stats } from "../api";
import type { TaxonomyMap } from "../lib/taxonomy";
import { Badge } from "./ui/Badge";
import { cn, formatLabel } from "../lib/utils";
import { topicColorClass } from "../lib/badges";

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
    <div className="flex flex-col gap-2 p-3">
      <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
        Statistics
      </h3>

      <div className="flex items-center gap-2 flex-wrap">
        <Badge
          variant="secondary"
          title="Show all segments"
          onClick={() => onFiltersChange({ ...filters, status: undefined })}
          className={cn(!filters.status && "ring-1 ring-primary")}
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
          className={cn(filters.status === "reviewed" && "ring-1 ring-primary")}
        >
          <span className="inline-block w-2 h-2 rounded-full bg-green-500 mr-1" />
          {stats?.reviewed ?? 0} reviewed
        </Badge>
        <Badge
          variant="secondary"
          title="Filter segments pending review"
          onClick={() =>
            onFiltersChange({
              ...filters,
              status: filters.status === "unreviewed" ? undefined : "unreviewed",
            })
          }
          className={cn(filters.status === "unreviewed" && "ring-1 ring-primary")}
        >
          <span className="inline-block w-2 h-2 rounded-full bg-yellow-500 mr-1" />
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
                  onFiltersChange({ ...filters, topic: active ? undefined : topic })
                }
                className={cn(
                  "flex items-center gap-2 rounded-md px-1 py-0.5 transition-colors hover:bg-secondary/60",
                  active && "bg-secondary",
                )}
                title={`Filter by ${formatLabel(topic)}`}
              >
                <span className="w-28 shrink-0 truncate text-left text-[11px]">
                  {taxonomy[topic]?.name ?? formatLabel(topic)}
                </span>
                <span className="relative flex-1 h-2 rounded-full bg-secondary/60 overflow-hidden">
                  <span
                    className={cn(
                      "absolute inset-y-0 left-0 rounded-full border",
                      topicColorClass(topic),
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
