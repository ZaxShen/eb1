import type { Stats } from "../api";

interface StatsBarProps {
  stats: Stats | null;
}

export default function StatsBar({ stats }: StatsBarProps) {
  if (!stats) {
    return (
      <div className="border-b border-slate-200 bg-slate-50 px-4 py-2 text-sm text-slate-500">
        No stats loaded.
      </div>
    );
  }

  const topics = Object.entries(stats.per_topic).sort((a, b) => b[1] - a[1]);

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-slate-200 bg-slate-50 px-4 py-2 text-sm">
      <span className="font-semibold text-slate-700">
        {stats.reviewed}/{stats.total} reviewed
      </span>
      <span className="text-slate-500">{stats.unreviewed} unreviewed</span>
      <span className="text-slate-300">|</span>
      {topics.length === 0 ? (
        <span className="text-slate-400">no topics</span>
      ) : (
        topics.map(([topic, count]) => (
          <span key={topic} className="text-slate-500">
            <span className="font-medium text-slate-700">{topic}</span> {count}
          </span>
        ))
      )}
    </div>
  );
}
