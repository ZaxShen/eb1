import type { ReactNode } from "react";
import type { SegmentSummary } from "../api";
import { Badge } from "./ui/Badge";
import { cn, formatConfidence, formatLabel } from "../lib/utils";
import { sentimentBadgeClass, SUBTOPIC_BADGE_CLASS, topicColorClass } from "../lib/badges";

interface SegmentFieldsPanelProps {
  segment: SegmentSummary | null;
}

const FieldRow = ({ label, children }: { label: string; children: ReactNode }) => (
  <>
    <dt className="text-xs text-muted-foreground">{label}</dt>
    <dd className="text-xs text-foreground break-all">{children}</dd>
  </>
);

const SegmentFieldsPanel = ({ segment }: SegmentFieldsPanelProps) => {
  if (!segment) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Select a segment
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="px-3 py-2">
        <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
          Segment Fields
        </h3>
      </div>
      <div className="flex-1 overflow-y-auto px-3 pb-3">
        <dl className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-1.5">
          <FieldRow label="id">
            <span className="font-mono">{segment.id}</span>
          </FieldRow>
          <FieldRow label="conversation">
            <span className="font-mono">{segment.conversation}</span>
          </FieldRow>
          <FieldRow label="chunk_index">
            <span className="font-mono">{segment.chunk_index}</span>
          </FieldRow>
          <FieldRow label="message_indices">
            <span className="font-mono">[{segment.message_indices.join(", ")}]</span>
          </FieldRow>
          <FieldRow label="topic">
            {segment.topic ? (
              <Badge variant="secondary" className={cn("border", topicColorClass(segment.topic))}>
                {formatLabel(segment.topic)}
              </Badge>
            ) : (
              "—"
            )}
          </FieldRow>
          <FieldRow label="subtopic">
            {segment.subtopic ? (
              <Badge variant="outline" className={SUBTOPIC_BADGE_CLASS}>
                {formatLabel(segment.subtopic)}
              </Badge>
            ) : (
              "—"
            )}
          </FieldRow>
          <FieldRow label="sentiment">
            {segment.sentiment ? (
              <Badge variant="outline" className={cn("border", sentimentBadgeClass(segment.sentiment))}>
                {segment.sentiment}
              </Badge>
            ) : (
              "—"
            )}
          </FieldRow>
          <FieldRow label="label_confidence">
            {formatConfidence(segment.label_confidence)}
          </FieldRow>
          <FieldRow label="summary">{segment.summary ?? "—"}</FieldRow>
          <FieldRow label="reviewed">{segment.reviewed ? "Yes" : "No"}</FieldRow>
        </dl>
      </div>
    </div>
  );
};

export default SegmentFieldsPanel;
