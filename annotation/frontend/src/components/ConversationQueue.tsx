import { useEffect, useRef, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  MessagesSquare,
  RotateCcw,
  Search,
  Sparkles,
  Tag,
  User,
} from "lucide-react";
import type {
  BertopicLabels,
  ConversationFilters,
  ConversationSummary,
} from "../api";
import type { TaxonomyMap } from "../lib/taxonomy";
import { sortedTopics } from "../lib/taxonomy";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
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
import { cn, formatLabel } from "../lib/utils";

interface ConversationQueueProps {
  conversations: ConversationSummary[];
  selectedConversation: string | null;
  filters: ConversationFilters;
  search: string;
  page: number;
  pageSize: number;
  total: number;
  taxonomy: TaxonomyMap;
  bertopicLabels: BertopicLabels;
  loading: boolean;
  onSelect: (conversation: string) => void;
  onFiltersChange: (filters: ConversationFilters) => void;
  onSearchChange: (q: string) => void;
  onPageChange: (page: number) => void;
}

const ALL_TOPICS = "__all__";
const SEARCH_DEBOUNCE_MS = 300;

const ConversationCard = ({
  conversation,
  isSelected,
  onClick,
}: {
  conversation: ConversationSummary;
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
        {conversation.conversation}
      </span>
      {conversation.reviewed && (
        <span
          className="size-2 shrink-0 rounded-full bg-positive"
          title="All segments reviewed"
        />
      )}
    </div>

    <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
      <span className="flex items-center gap-1">
        <MessagesSquare className="size-3" />
        {conversation.message_count} msg
      </span>
      <span>
        {conversation.segment_count} segment
        {conversation.segment_count !== 1 ? "s" : ""}
      </span>
      <span>
        {conversation.reviewed_count}/{conversation.segment_count} reviewed
      </span>
    </div>
  </button>
);

const ConversationQueue = ({
  conversations,
  selectedConversation,
  filters,
  search,
  page,
  pageSize,
  total,
  taxonomy,
  bertopicLabels,
  loading,
  onSelect,
  onFiltersChange,
  onSearchChange,
  onPageChange,
}: ConversationQueueProps) => {
  const topics = sortedTopics(taxonomy);
  const update = (patch: Partial<ConversationFilters>) =>
    onFiltersChange({ ...filters, ...patch });

  // BERTopic subtopic options narrow to the picked topic's children; with no
  // topic chosen every subtopic is offered.
  const bertopicSubtopics = filters.bertopic_topic
    ? bertopicLabels.subtopics.filter(
        (s) => s.topic === filters.bertopic_topic,
      )
    : bertopicLabels.subtopics;

  // Local mirror of the search box so typing is instant; the committed `q`
  // (which triggers a server refetch) is debounced off it.
  const [searchInput, setSearchInput] = useState(search);
  const onSearchChangeRef = useRef(onSearchChange);
  onSearchChangeRef.current = onSearchChange;

  // Keep the input in sync when `search` is reset externally (e.g. dataset swap).
  useEffect(() => {
    setSearchInput(search);
  }, [search]);

  useEffect(() => {
    if (searchInput === search) return;
    const handle = setTimeout(() => {
      onSearchChangeRef.current(searchInput);
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [searchInput, search]);

  const hasActiveFilters =
    filters.status !== undefined ||
    filters.topic !== undefined ||
    filters.bertopic_topic !== undefined ||
    filters.bertopic_subtopic !== undefined ||
    search !== "";

  const statusOptions: {
    value: ConversationFilters["status"];
    label: string;
  }[] = [
    { value: undefined, label: "All" },
    { value: "unreviewed", label: "Unreviewed" },
    { value: "reviewed", label: "Reviewed" },
  ];

  const pageCount = total > 0 ? Math.ceil(total / pageSize) : 1;
  const rangeStart = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const rangeEnd = Math.min(page * pageSize, total);

  const resetAll = () => {
    setSearchInput("");
    onSearchChange("");
    onFiltersChange({});
  };

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex flex-col gap-2.5 p-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold tracking-tight">
            Conversations
          </h2>
          {hasActiveFilters && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="icon-xs" onClick={resetAll}>
                  <RotateCcw />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Reset search and filters</TooltipContent>
            </Tooltip>
          )}
        </div>

        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            type="search"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search conversations…"
            aria-label="Search conversations"
            className="pl-8"
          />
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

        <Select
          value={filters.bertopic_topic ?? ALL_TOPICS}
          onValueChange={(v) => {
            const next = v === ALL_TOPICS ? undefined : v;
            // A topic switch invalidates a subtopic that isn't its child.
            const keepSub =
              filters.bertopic_subtopic !== undefined &&
              (next === undefined ||
                bertopicLabels.subtopics.some(
                  (s) =>
                    s.subtopic === filters.bertopic_subtopic &&
                    s.topic === next,
                ));
            update({
              bertopic_topic: next,
              bertopic_subtopic: keepSub
                ? filters.bertopic_subtopic
                : undefined,
            });
          }}
        >
          <SelectTrigger
            size="sm"
            className="w-full"
            aria-label="BERTopic topic"
          >
            <Sparkles className="size-3.5 text-muted-foreground" />
            <SelectValue placeholder="All BERTopic topics" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_TOPICS}>All BERTopic topics</SelectItem>
            {bertopicLabels.topics.map((t) => (
              <SelectItem key={t.topic} value={t.topic}>
                {formatLabel(t.topic)} ({t.count})
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select
          value={filters.bertopic_subtopic ?? ALL_TOPICS}
          onValueChange={(v) =>
            update({ bertopic_subtopic: v === ALL_TOPICS ? undefined : v })
          }
        >
          <SelectTrigger
            size="sm"
            className="w-full"
            aria-label="BERTopic subtopic"
          >
            <Sparkles className="size-3.5 text-muted-foreground" />
            <SelectValue placeholder="All BERTopic subtopics" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_TOPICS}>All BERTopic subtopics</SelectItem>
            {bertopicSubtopics.map((s) => (
              <SelectItem key={s.subtopic} value={s.subtopic}>
                {formatLabel(s.subtopic)} ({s.count})
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <Separator />

      <ScrollArea className="min-h-0 flex-1">
        <div className="p-2">
          {loading && (
            <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
              Loading…
            </div>
          )}
          {!loading && conversations.length === 0 && (
            <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
              No conversations found
            </div>
          )}
          {!loading && conversations.length > 0 && (
            <div className="flex flex-col gap-1">
              {conversations.map((conversation) => (
                <ConversationCard
                  key={conversation.conversation}
                  conversation={conversation}
                  isSelected={
                    selectedConversation === conversation.conversation
                  }
                  onClick={() => onSelect(conversation.conversation)}
                />
              ))}
            </div>
          )}
        </div>
      </ScrollArea>

      <Separator />

      <div className="flex items-center justify-between gap-2 px-3 py-2">
        <span className="text-xs text-muted-foreground" aria-live="polite">
          {total === 0 ? (
            "0 conversations"
          ) : (
            <>
              {rangeStart}–{rangeEnd} of {total.toLocaleString()}
            </>
          )}
        </span>
        <div className="flex items-center gap-1">
          <Button
            variant="outline"
            size="icon-xs"
            onClick={() => onPageChange(page - 1)}
            disabled={loading || page <= 1}
            aria-label="Previous page"
          >
            <ChevronLeft />
          </Button>
          <span className="min-w-[3.5rem] text-center text-xs text-muted-foreground tabular-nums">
            {page} / {pageCount}
          </span>
          <Button
            variant="outline"
            size="icon-xs"
            onClick={() => onPageChange(page + 1)}
            disabled={loading || page >= pageCount}
            aria-label="Next page"
          >
            <ChevronRight />
          </Button>
        </div>
      </div>
    </div>
  );
};

export default ConversationQueue;
