import type { ReactNode } from "react";
import { Check, ChevronLeft, ChevronRight, Save } from "lucide-react";
import type { SegmentSummary } from "../api";
import type { TaxonomyMap } from "../lib/taxonomy";
import { sortedTopics, subtopicsFor } from "../lib/taxonomy";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { formatLabel } from "../lib/utils";

interface AnnotationPanelProps {
  segment: SegmentSummary | null;
  taxonomy: TaxonomyMap;
  topic: string;
  subtopic: string;
  reviewedBy: string;
  reviewedByLocked?: boolean;
  saving: boolean;
  onTopicChange: (topic: string) => void;
  onSubtopicChange: (subtopic: string) => void;
  onReviewedByChange: (value: string) => void;
  onConfirmAi: () => void;
  onSave: () => void;
  onPrev: () => void;
  onNext: () => void;
}

const Kbd = ({ children }: { children: ReactNode }) => (
  <kbd className="inline-flex h-4 items-center rounded border border-border bg-muted px-1 text-[0.625rem] font-medium text-muted-foreground">
    {children}
  </kbd>
);

const AnnotationPanel = ({
  segment,
  taxonomy,
  topic,
  subtopic,
  reviewedBy,
  reviewedByLocked = false,
  saving,
  onTopicChange,
  onSubtopicChange,
  onReviewedByChange,
  onConfirmAi,
  onSave,
  onPrev,
  onNext,
}: AnnotationPanelProps) => {
  if (!segment) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Select a segment in the stream
      </div>
    );
  }

  const topics = sortedTopics(taxonomy);
  const subtopics = subtopicsFor(taxonomy, topic);
  const aiTopic = segment.topic;

  return (
    <div className="flex h-full flex-col overflow-y-auto p-3">
      <h3 className="mb-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        Annotation
      </h3>

      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <label className="text-xs text-muted-foreground">True Topic</label>
          <Select value={topic} onValueChange={onTopicChange}>
            <SelectTrigger size="sm" className="w-full">
              <SelectValue placeholder="Select a topic…" />
            </SelectTrigger>
            <SelectContent>
              {topics.map((t) => (
                <SelectItem key={t} value={t}>
                  {taxonomy[t]?.name ?? formatLabel(t)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-xs text-muted-foreground">True Subtopic</label>
          <Select
            value={subtopic}
            onValueChange={onSubtopicChange}
            disabled={!topic || subtopics.length === 0}
          >
            <SelectTrigger size="sm" className="w-full">
              <SelectValue
                placeholder={
                  topic ? "Select a subtopic…" : "Select a topic first"
                }
              />
            </SelectTrigger>
            <SelectContent>
              {subtopics.map((s) => (
                <SelectItem key={s} value={s}>
                  {formatLabel(s)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-xs text-muted-foreground">
            {reviewedByLocked ? "Reviewed by (Google account)" : "Reviewed by (optional)"}
          </label>
          {reviewedByLocked ? (
            <div className="flex h-8 items-center rounded-md border border-border bg-muted px-3 text-sm text-muted-foreground">
              {reviewedBy}
            </div>
          ) : (
            <Input
              value={reviewedBy}
              onChange={(e) => onReviewedByChange(e.target.value)}
              placeholder="your name"
              className="h-8 text-sm"
            />
          )}
        </div>

        <Separator />

        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            className="flex-1"
            onClick={onConfirmAi}
            disabled={!aiTopic}
            title="Confirm the AI label (Space)"
          >
            <Check />
            Confirm AI
            <Kbd>Space</Kbd>
          </Button>
          <Button
            size="sm"
            className="flex-1"
            onClick={onSave}
            disabled={saving || !topic}
            title="Save annotation (Enter)"
          >
            <Save />
            {saving ? "Saving…" : "Save"}
            {!saving && <Kbd>Enter</Kbd>}
          </Button>
        </div>

        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            className="flex-1"
            onClick={onPrev}
            title="Previous conversation (←)"
          >
            <ChevronLeft />
            Prev
            <Kbd>←</Kbd>
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="flex-1"
            onClick={onNext}
            title="Next conversation (→)"
          >
            Next
            <ChevronRight />
            <Kbd>→</Kbd>
          </Button>
        </div>
      </div>
    </div>
  );
};

export default AnnotationPanel;
