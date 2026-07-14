import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  MousePointerClick,
  Save,
  X,
} from "lucide-react";
import { EmptyState } from "@/components/ui/empty-state";
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
import { formatLabel, slugify } from "../lib/utils";

interface AnnotationPanelProps {
  segment: SegmentSummary | null;
  taxonomy: TaxonomyMap;
  usedTopics?: string[];
  topic: string;
  subtopic: string;
  reviewedBy: string;
  reviewedByLocked?: boolean;
  saving: boolean;
  onAddTopic?: (topic: string) => void | Promise<void>;
  onAddSubtopic?: (topic: string, subtopic: string) => void | Promise<void>;
  onTopicChange: (topic: string) => void;
  onSubtopicChange: (subtopic: string) => void;
  onReviewedByChange: (value: string) => void;
  onSave: () => void;
  onPrev: () => void;
  onNext: () => void;
}

// Radix Select forbids an empty-string item value, so the trailing "add new"
// item uses a sentinel intercepted before it ever becomes the field's value.
const ADD_NEW = "__add_new__";

interface AddNewSelectProps {
  value: string;
  options: string[];
  onChange: (slug: string) => void;
  onAddNew: (slug: string) => void | Promise<void>;
  disabled?: boolean;
  placeholder: string;
  ariaLabel: string;
  addNewLabel: string;
  label: (slug: string) => string;
}

/**
 * A taxonomy-fed dropdown whose last item ("+ New …") reveals an inline text
 * input. Typed text is slug-previewed live and, on confirm, persisted via
 * `onAddNew` then selected — so a brand-new value normalizes exactly like a
 * picked one and immediately joins every annotator's options.
 */
function AddNewSelect({
  value,
  options,
  onChange,
  onAddNew,
  disabled,
  placeholder,
  ariaLabel,
  addNewLabel,
  label,
}: AddNewSelectProps) {
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState("");
  const slug = slugify(draft);

  // Keep the current value visible even when it is not (yet) a taxonomy option.
  const allOptions = useMemo(() => {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const o of [...(value ? [value] : []), ...options]) {
      if (o && !seen.has(o)) {
        seen.add(o);
        out.push(o);
      }
    }
    return out;
  }, [value, options]);

  const cancel = () => {
    setAdding(false);
    setDraft("");
  };

  const confirm = async () => {
    if (!slug) return;
    await onAddNew(slug);
    cancel();
  };

  return (
    <div className="flex flex-col gap-1.5">
      <Select
        value={value}
        onValueChange={(v) => {
          if (v === ADD_NEW) {
            setDraft("");
            setAdding(true);
          } else {
            onChange(v);
          }
        }}
        disabled={disabled}
      >
        <SelectTrigger size="sm" className="w-full" aria-label={ariaLabel}>
          <SelectValue placeholder={placeholder} />
        </SelectTrigger>
        <SelectContent>
          {allOptions.map((o) => (
            <SelectItem key={o} value={o}>
              {label(o)}
            </SelectItem>
          ))}
          <SelectItem value={ADD_NEW}>{addNewLabel}</SelectItem>
        </SelectContent>
      </Select>

      {adding && (
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-1.5">
            <Input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  void confirm();
                } else if (e.key === "Escape") {
                  cancel();
                }
              }}
              placeholder="New name…"
              aria-label={`${ariaLabel} new name`}
              className="h-8 text-sm"
              autoFocus
            />
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => void confirm()}
              disabled={!slug}
              aria-label={`Confirm new ${ariaLabel}`}
            >
              <Check />
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={cancel}
              aria-label={`Cancel new ${ariaLabel}`}
            >
              <X />
            </Button>
          </div>
          {draft.trim() !== "" && (
            <span className="text-[11px] text-muted-foreground">
              Saves as{" "}
              <code className="rounded bg-muted px-1 py-0.5 text-foreground">
                {slug || "—"}
              </code>
            </span>
          )}
        </div>
      )}
    </div>
  );
}

const Kbd = ({ children }: { children: ReactNode }) => (
  <kbd className="inline-flex h-4 items-center rounded border border-border bg-muted px-1 text-[0.625rem] font-medium text-muted-foreground">
    {children}
  </kbd>
);

const AnnotationPanel = ({
  segment,
  taxonomy,
  usedTopics = [],
  topic,
  subtopic,
  reviewedBy,
  reviewedByLocked = false,
  saving,
  onAddTopic,
  onAddSubtopic,
  onTopicChange,
  onSubtopicChange,
  onReviewedByChange,
  onSave,
  onPrev,
  onNext,
}: AnnotationPanelProps) => {
  const taxonomyTopics = useMemo(() => sortedTopics(taxonomy), [taxonomy]);

  // Dropdown options: taxonomy names first, then any topics already used for
  // this dataset that the taxonomy doesn't cover, de-duplicated.
  const topicOptions = useMemo(() => {
    const seen = new Set(taxonomyTopics);
    return [...taxonomyTopics, ...usedTopics.filter((t) => !seen.has(t))];
  }, [taxonomyTopics, usedTopics]);

  // Copy the segment's source (BERTopic) labels into the True Topic/Subtopic
  // pickers as slugs — the taxonomy was seeded from these same labels. A null
  // source subtopic clears the subtopic field. Values are set, NOT saved; the
  // annotator still presses Save/Enter.
  const sourceTopic = segment?.bertopic_topic ?? null;
  const confirmSource = () => {
    if (!sourceTopic) return;
    onTopicChange(slugify(sourceTopic));
    onSubtopicChange(
      segment?.bertopic_subtopic ? slugify(segment.bertopic_subtopic) : "",
    );
  };
  const confirmSourceRef = useRef(confirmSource);
  confirmSourceRef.current = confirmSource;

  // Space confirms the source label from anywhere, except while an input or a
  // Radix combobox/listbox holds focus (same suppression rule the old Confirm
  // AI shortcut used) so it never eats a space typed into a field.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== " ") return;
      const el = e.target as HTMLElement | null;
      const tag = el?.tagName;
      const typing =
        tag === "INPUT" ||
        tag === "SELECT" ||
        tag === "TEXTAREA" ||
        el?.isContentEditable === true ||
        el?.getAttribute("role") === "combobox" ||
        el?.closest("[data-radix-popper-content-wrapper]") != null;
      if (typing) return;
      e.preventDefault();
      confirmSourceRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (!segment) {
    return (
      <EmptyState
        icon={MousePointerClick}
        title="Select a segment in the stream"
        hint="Click a segment to edit its topic and labels."
      />
    );
  }

  const subtopics = subtopicsFor(taxonomy, topic);

  return (
    <div className="flex h-full flex-col overflow-y-auto p-3">
      <h3 className="mb-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        Annotation
      </h3>

      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <label className="text-xs text-muted-foreground">True Topic</label>
          <AddNewSelect
            value={topic}
            options={topicOptions}
            onChange={onTopicChange}
            onAddNew={async (slug) => {
              await onAddTopic?.(slug);
              onTopicChange(slug);
            }}
            placeholder="Select a topic…"
            ariaLabel="True Topic"
            addNewLabel="+ New topic…"
            label={(t) => taxonomy[t]?.name ?? formatLabel(t)}
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-xs text-muted-foreground">True Subtopic</label>
          <AddNewSelect
            value={subtopic}
            options={subtopics}
            onChange={onSubtopicChange}
            onAddNew={async (slug) => {
              await onAddSubtopic?.(topic, slug);
              onSubtopicChange(slug);
            }}
            disabled={!topic}
            placeholder={topic ? "Select a subtopic…" : "Select a topic first"}
            ariaLabel="True Subtopic"
            addNewLabel="+ New subtopic…"
            label={(s) => formatLabel(s)}
          />
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
            onClick={confirmSource}
            disabled={!sourceTopic}
            title="Confirm the source label (Space)"
          >
            <Check />
            Confirm source
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
