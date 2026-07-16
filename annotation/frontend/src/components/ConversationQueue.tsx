import { useEffect, useMemo, useRef, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Inbox,
  Landmark,
  MessagesSquare,
  RotateCcw,
  Search,
  Sparkles,
  User,
} from "lucide-react";
import type {
  BertopicLabels,
  ConversationFilters,
  ConversationSummary,
} from "../api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
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
import { topicColorClass } from "../lib/badges";
import { DOMAINS } from "../lib/domains";
import { cn, formatLabel } from "../lib/utils";

interface ConversationQueueProps {
  conversations: ConversationSummary[];
  selectedConversation: string | null;
  filters: ConversationFilters;
  search: string;
  page: number;
  pageSize: number;
  total: number;
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
}) => {
  const { message_count, segment_count, reviewed_count, topics } = conversation;
  const reviewPct =
    segment_count > 0 ? Math.round((reviewed_count / segment_count) * 100) : 0;
  const inProgress = reviewed_count > 0 && reviewed_count < segment_count;

  return (
    <button
      onClick={onClick}
      className={cn(
        "group w-full rounded-lg border px-2.5 py-2.5 text-left transition-colors hover:bg-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        isSelected
          ? "border-primary/40 bg-accent ring-1 ring-primary/30"
          : "border-transparent",
      )}
    >
      <div className="flex items-center gap-2">
        <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-secondary text-muted-foreground transition-colors group-hover:bg-background">
          <User className="size-3.5" />
        </span>
        <span className="flex-1 truncate font-mono text-[13px] font-medium tracking-tight">
          {conversation.conversation}
        </span>
        {conversation.reviewed && (
          <span
            className="size-2 shrink-0 rounded-full bg-positive ring-2 ring-positive/20"
            title="All segments reviewed"
          />
        )}
      </div>

      {topics.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {topics.slice(0, 3).map((t) => (
            <span
              key={t}
              className={cn(
                "rounded-full border px-1.5 py-px text-[10px] font-medium leading-tight",
                topicColorClass(t),
              )}
            >
              {formatLabel(t)}
            </span>
          ))}
          {topics.length > 3 && (
            <span className="text-[10px] leading-5 text-muted-foreground">
              +{topics.length - 3}
            </span>
          )}
        </div>
      )}

      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span className="flex items-center gap-1">
          <MessagesSquare className="size-3" />
          {message_count} msg
        </span>
        <span>
          {segment_count} segment{segment_count !== 1 ? "s" : ""}
        </span>
        {inProgress && (
          <span className="ml-auto flex items-center gap-1.5">
            <span className="h-1 w-10 overflow-hidden rounded-full bg-muted">
              <span
                className="block h-full rounded-full bg-primary/70"
                style={{ width: `${reviewPct}%` }}
              />
            </span>
            <span className="tabular-nums">
              {reviewed_count}/{segment_count}
            </span>
          </span>
        )}
      </div>
    </button>
  );
};

const ConversationQueue = ({
  conversations,
  selectedConversation,
  filters,
  search,
  page,
  pageSize,
  total,
  bertopicLabels,
  loading,
  onSelect,
  onFiltersChange,
  onSearchChange,
  onPageChange,
}: ConversationQueueProps) => {
  const update = (patch: Partial<ConversationFilters>) =>
    onFiltersChange({ ...filters, ...patch });

  const selectedDomain = filters.domain;

  // Topic (nav category) options cascade off the chosen domain: with a domain
  // picked only that domain's categories show; with none picked every category
  // shows, de-duplicated by name across domains (counts summed) so the same
  // category living in two domains ("Disability") is a single, unique option.
  const topicOptions = useMemo(() => {
    const source = selectedDomain
      ? bertopicLabels.topics.filter((t) => t.domain === selectedDomain)
      : bertopicLabels.topics;
    if (selectedDomain) return source.map((t) => ({ label: t.topic, count: t.count }));
    const byName = new Map<string, number>();
    for (const t of source) byName.set(t.topic, (byName.get(t.topic) ?? 0) + t.count);
    return [...byName.entries()].map(([label, count]) => ({ label, count }));
  }, [bertopicLabels.topics, selectedDomain]);

  // Source subtopic options narrow to the picked domain then the picked topic's
  // children; with neither chosen every subtopic is offered (de-duplicated).
  const subtopicOptions = useMemo(() => {
    let source = bertopicLabels.subtopics;
    if (selectedDomain) source = source.filter((s) => s.domain === selectedDomain);
    if (filters.bertopic_topic)
      source = source.filter((s) => s.topic === filters.bertopic_topic);
    const byName = new Map<string, number>();
    for (const s of source)
      byName.set(s.subtopic, (byName.get(s.subtopic) ?? 0) + s.count);
    return [...byName.entries()].map(([label, count]) => ({ label, count }));
  }, [bertopicLabels.subtopics, selectedDomain, filters.bertopic_topic]);

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
    filters.domain !== undefined ||
    filters.bertopic_topic !== undefined ||
    filters.bertopic_subtopic !== undefined ||
    filters.mismatch === true ||
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
          value={filters.domain ?? ALL_TOPICS}
          onValueChange={(v) => {
            const next = v === ALL_TOPICS ? undefined : v;
            // A domain switch scopes the categories, so any picked topic/subtopic
            // from the previous domain is dropped.
            update({
              domain: next,
              bertopic_topic: undefined,
              bertopic_subtopic: undefined,
            });
          }}
        >
          <SelectTrigger size="sm" className="w-full" aria-label="Domain">
            <Landmark className="size-3.5 text-muted-foreground" />
            <SelectValue placeholder="All domains" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_TOPICS}>All domains</SelectItem>
            {DOMAINS.map((d) => (
              <SelectItem key={d.code} value={d.code}>
                {d.label}
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
          <SelectTrigger size="sm" className="w-full" aria-label="Topic">
            <Sparkles className="size-3.5 text-muted-foreground" />
            <SelectValue placeholder="All topics" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_TOPICS}>All topics</SelectItem>
            {topicOptions.map((t) => (
              <SelectItem key={t.label} value={t.label}>
                <span className="flex-1 min-w-0 truncate">
                  {formatLabel(t.label)}
                </span>
                <span className="text-muted-foreground text-xs tabular-nums">
                  {t.count}
                </span>
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
          <SelectTrigger size="sm" className="w-full" aria-label="Subtopic">
            <Sparkles className="size-3.5 text-muted-foreground" />
            <SelectValue placeholder="All subtopics" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_TOPICS}>All subtopics</SelectItem>
            {subtopicOptions.map((s) => (
              <SelectItem key={s.label} value={s.label}>
                <span className="flex-1 min-w-0 truncate">
                  {formatLabel(s.label)}
                </span>
                <span className="text-muted-foreground text-xs tabular-nums">
                  {s.count}
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <Separator />

      <ScrollArea className="min-h-0 flex-1">
        <div className="p-2">
          {loading && (
            <div className="flex flex-col gap-1">
              {Array.from({ length: 7 }).map((_, i) => (
                <div key={i} className="rounded-lg px-2.5 py-2.5">
                  <div className="flex items-center gap-2">
                    <Skeleton className="size-6 shrink-0 rounded-full" />
                    <Skeleton className="h-3.5 w-40" />
                  </div>
                  <Skeleton className="mt-2 h-2.5 w-28" />
                </div>
              ))}
            </div>
          )}
          {!loading && conversations.length === 0 && (
            <div className="flex h-40 flex-col items-center justify-center gap-2 px-4 text-center">
              <span className="flex size-10 items-center justify-center rounded-full bg-muted text-muted-foreground">
                <Inbox className="size-5" />
              </span>
              <p className="text-sm font-medium">No conversations found</p>
              <p className="text-xs text-muted-foreground">
                {hasActiveFilters
                  ? "Try clearing search or filters."
                  : "Nothing in this dataset yet."}
              </p>
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
