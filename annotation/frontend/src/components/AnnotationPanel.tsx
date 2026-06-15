import type { SegmentDetail } from "../api";
import type { TaxonomyMap } from "../lib/taxonomy";
import { sortedTopics, subtopicsFor } from "../lib/taxonomy";
import { Button, Kbd } from "./ui/Button";
import { ChevronLeft, ChevronRight } from "./icons";
import { formatLabel } from "../lib/utils";
import { topicTextColor } from "../lib/badges";

interface AnnotationPanelProps {
  detail: SegmentDetail | null;
  taxonomy: TaxonomyMap;
  topic: string;
  subtopic: string;
  reviewedBy: string;
  saving: boolean;
  onTopicChange: (topic: string) => void;
  onSubtopicChange: (subtopic: string) => void;
  onReviewedByChange: (value: string) => void;
  onConfirmAi: () => void;
  onSave: () => void;
  onPrev: () => void;
  onNext: () => void;
}

const AnnotationPanel = ({
  detail,
  taxonomy,
  topic,
  subtopic,
  reviewedBy,
  saving,
  onTopicChange,
  onSubtopicChange,
  onReviewedByChange,
  onConfirmAi,
  onSave,
  onPrev,
  onNext,
}: AnnotationPanelProps) => {
  if (!detail) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Select a segment from the queue
      </div>
    );
  }

  const topics = sortedTopics(taxonomy);
  const subtopics = subtopicsFor(taxonomy, topic);
  const aiTopic = detail.segment.topic;

  return (
    <div className="flex h-full flex-col overflow-y-auto p-3">
      <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
        Annotation
      </h3>

      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">True Topic</label>
          <select
            value={topic}
            onChange={(e) => onTopicChange(e.target.value)}
            className="rounded-md border border-border bg-background px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          >
            <option value="">Select a topic…</option>
            {topics.map((t) => (
              <option key={t} value={t} className={topicTextColor(t)}>
                {taxonomy[t]?.name ?? formatLabel(t)}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">True Subtopic</label>
          <select
            value={subtopic}
            onChange={(e) => onSubtopicChange(e.target.value)}
            disabled={!topic || subtopics.length === 0}
            className="rounded-md border border-border bg-background px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50"
          >
            <option value="">
              {topic ? "Select a subtopic…" : "Select a topic first"}
            </option>
            {subtopics.map((s) => (
              <option key={s} value={s}>
                {formatLabel(s)}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">Reviewed by (optional)</label>
          <input
            value={reviewedBy}
            onChange={(e) => onReviewedByChange(e.target.value)}
            placeholder="your name"
            className="rounded-md border border-border bg-background px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
        </div>

        <div className="flex gap-2">
          <Button
            variant="outline"
            className="flex-1"
            onClick={onConfirmAi}
            disabled={!aiTopic}
            title="Confirm the AI label (Space)"
          >
            Confirm AI
            <Kbd>Space</Kbd>
          </Button>
          <Button
            variant="primary"
            className="flex-1"
            onClick={onSave}
            disabled={saving || !topic}
            title="Save annotation (Enter)"
          >
            {saving ? "Saving…" : "Save"}
            {!saving && <Kbd>Enter</Kbd>}
          </Button>
        </div>

        <div className="flex gap-2">
          <Button variant="outline" className="flex-1" onClick={onPrev} title="Previous segment (←)">
            <ChevronLeft className="h-4 w-4" />
            Prev
            <Kbd>←</Kbd>
          </Button>
          <Button variant="outline" className="flex-1" onClick={onNext} title="Next segment (→)">
            Next
            <ChevronRight className="h-4 w-4" />
            <Kbd>→</Kbd>
          </Button>
        </div>
      </div>
    </div>
  );
};

export default AnnotationPanel;
