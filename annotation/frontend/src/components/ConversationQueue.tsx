import { MessagesSquare, RotateCcw, Tag, User } from "lucide-react";
import type { ConversationFilters, ConversationSummary } from "../api";
import type { TaxonomyMap } from "../lib/taxonomy";
import { sortedTopics } from "../lib/taxonomy";
import { Button } from "@/components/ui/button";
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
  taxonomy: TaxonomyMap;
  loading: boolean;
  total: number;
  onSelect: (conversation: string) => void;
  onFiltersChange: (filters: ConversationFilters) => void;
}

const ALL_TOPICS = "__all__";

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
  taxonomy,
  loading,
  total,
  onSelect,
  onFiltersChange,
}: ConversationQueueProps) => {
  const topics = sortedTopics(taxonomy);
  const update = (patch: Partial<ConversationFilters>) =>
    onFiltersChange({ ...filters, ...patch });

  const hasActiveFilters =
    filters.status !== undefined || filters.topic !== undefined;

  const statusOptions: {
    value: ConversationFilters["status"];
    label: string;
  }[] = [
    { value: undefined, label: "All" },
    { value: "unreviewed", label: "Unreviewed" },
    { value: "reviewed", label: "Reviewed" },
  ];

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
                <Button
                  variant="ghost"
                  size="icon-xs"
                  onClick={() => onFiltersChange({})}
                >
                  <RotateCcw />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Reset all filters</TooltipContent>
            </Tooltip>
          )}
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
      <div className="px-4 py-1.5 text-center text-xs text-muted-foreground">
        {conversations.length} shown · {total} total conversation
        {total !== 1 ? "s" : ""}
      </div>
    </div>
  );
};

export default ConversationQueue;
