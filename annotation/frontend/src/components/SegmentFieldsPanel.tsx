import { Fragment, type ReactNode } from "react";
import type { SegmentSummary } from "../api";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { formatConfidence, formatLabel } from "../lib/utils";
import {
  sentimentBadgeClass,
  SUBTOPIC_BADGE_CLASS,
  topicColorClass,
} from "../lib/badges";

interface SegmentFieldsPanelProps {
  segment: SegmentSummary | null;
}

const FieldRow = ({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) => (
  <div className="flex items-start justify-between gap-3 py-1.5">
    <dt className="shrink-0 text-xs text-muted-foreground">{label}</dt>
    <dd className="break-all text-right text-xs text-foreground">{children}</dd>
  </div>
);

const SegmentFieldsPanel = ({ segment }: SegmentFieldsPanelProps) => {
  if (!segment) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Select a segment
      </div>
    );
  }

  const rows: { label: string; node: ReactNode }[] = [
    { label: "id", node: <span className="font-mono">{segment.id}</span> },
    {
      label: "conversation",
      node: <span className="font-mono">{segment.conversation}</span>,
    },
    {
      label: "chunk_index",
      node: <span className="font-mono">{segment.chunk_index}</span>,
    },
    {
      label: "message_indices",
      node: (
        <span className="font-mono">[{segment.message_indices.join(", ")}]</span>
      ),
    },
    {
      label: "topic",
      node: segment.topic ? (
        <Badge variant="outline" className={topicColorClass(segment.topic)}>
          {formatLabel(segment.topic)}
        </Badge>
      ) : (
        "—"
      ),
    },
    {
      label: "subtopic",
      node: segment.subtopic ? (
        <Badge variant="outline" className={SUBTOPIC_BADGE_CLASS}>
          {formatLabel(segment.subtopic)}
        </Badge>
      ) : (
        "—"
      ),
    },
    {
      label: "sentiment",
      node: segment.sentiment ? (
        <Badge
          variant="outline"
          className={sentimentBadgeClass(segment.sentiment)}
        >
          {segment.sentiment}
        </Badge>
      ) : (
        "—"
      ),
    },
    {
      label: "label_confidence",
      node: formatConfidence(segment.label_confidence),
    },
    { label: "summary", node: segment.summary ?? "—" },
    { label: "reviewed", node: segment.reviewed ? "Yes" : "No" },
  ];

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="px-3 py-2.5">
        <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          Segment Fields
        </h3>
      </div>
      <Separator />
      <ScrollArea className="min-h-0 flex-1">
        <dl className="px-3 py-1">
          {rows.map((row, i) => (
            <Fragment key={row.label}>
              {i > 0 && <Separator />}
              <FieldRow label={row.label}>{row.node}</FieldRow>
            </Fragment>
          ))}
        </dl>
      </ScrollArea>
    </div>
  );
};

export default SegmentFieldsPanel;
