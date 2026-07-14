import { useMemo } from "react";
import { ArrowUpToLine, MessagesSquare, Scissors } from "lucide-react";
import { EmptyState } from "@/components/ui/empty-state";
import type {
  ConversationView,
  Message,
  SegmentSummary,
} from "../api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { mergeWithPrevious, splitAt } from "../lib/boundaries";
import {
  sentimentBadgeClass,
  SUBTOPIC_BADGE_CLASS,
  topicColorClass,
} from "../lib/badges";
import {
  cn,
  formatChatTimestamp,
  formatLabel,
  hasSyntheticTimestamps,
  isSameMinute,
} from "../lib/utils";

// Bubble color-by-role, mirroring eb1-dev RoleStyleLight/Dark via semantic
// tokens: assistant=role-assistant, automated=role-automated, team=role-team,
// user/system=neutral secondary.
const ROLE_STYLE: Record<string, string> = {
  assistant: "bg-role-assistant/15 text-foreground",
  bot: "bg-role-assistant/15 text-foreground",
  automated: "bg-role-automated/15 text-foreground",
  team: "bg-role-team/15 text-foreground",
  user: "bg-secondary text-secondary-foreground",
  human: "bg-secondary text-secondary-foreground",
  system: "bg-secondary text-secondary-foreground",
};

function roleStyle(type: string): string {
  return ROLE_STYLE[type] ?? ROLE_STYLE.system;
}

function senderLabel(type: string): string {
  return type.charAt(0).toUpperCase() + type.slice(1);
}

function isUserRole(type: string): boolean {
  return type === "user" || type === "human" || type === "system";
}

const MessageBubble = ({
  msg,
  prevMsg,
  hideTimestamp = false,
  onSplitHere,
}: {
  msg: Message;
  prevMsg?: Message;
  hideTimestamp?: boolean;
  onSplitHere?: () => void;
}) => {
  const isUser = isUserRole(msg.type);
  const bubbleStyle = roleStyle(msg.type);
  const isFirstInSeries = !prevMsg || prevMsg.type !== msg.type;
  const showTimestamp =
    !hideTimestamp &&
    (isFirstInSeries || !isSameMinute(prevMsg?.createdAt, msg.createdAt));

  return (
    <div className="group flex flex-col gap-0.5">
      {(isFirstInSeries || showTimestamp) && (
        <div
          className={cn(
            "mb-0.5 mt-2 flex select-none items-center gap-1.5 px-3 text-[11px] text-muted-foreground",
            isUser ? "justify-start" : "justify-end",
          )}
        >
          {isFirstInSeries && <span>{senderLabel(msg.type)}</span>}
          {showTimestamp && msg.createdAt && (
            <span className="opacity-60">
              {formatChatTimestamp(msg.createdAt)}
            </span>
          )}
        </div>
      )}
      <div
        className={cn(
          "flex w-full items-end gap-1",
          isUser ? "flex-row" : "flex-row-reverse",
        )}
      >
        <div
          className={cn(
            "max-w-[80%] whitespace-pre-wrap break-words rounded-xl px-3 py-2 text-sm leading-relaxed",
            bubbleStyle,
            isUser ? "rounded-bl-sm" : "rounded-br-sm",
          )}
        >
          {msg.message}
        </div>
        {onSplitHere && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon-xs"
                onClick={(e) => {
                  e.stopPropagation();
                  onSplitHere();
                }}
                className="shrink-0 opacity-0 transition-opacity group-hover:opacity-100"
              >
                <Scissors />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Split a new segment starting here</TooltipContent>
          </Tooltip>
        )}
      </div>
    </div>
  );
};

const SegmentDivider = ({
  label,
  segment,
  current,
  onMergePrev,
}: {
  label: string;
  segment: SegmentSummary;
  current?: boolean;
  onMergePrev?: () => void;
}) => (
  <div className="flex w-full flex-row items-center gap-2 py-1">
    <div
      className={cn("h-px flex-1", current ? "bg-primary/40" : "bg-border")}
    />
    {onMergePrev && (
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="icon-xs"
            onClick={(e) => {
              e.stopPropagation();
              onMergePrev();
            }}
            className="shrink-0"
          >
            <ArrowUpToLine />
          </Button>
        </TooltipTrigger>
        <TooltipContent>Merge into the previous segment</TooltipContent>
      </Tooltip>
    )}
    <span
      className={cn(
        "shrink-0 font-medium",
        current
          ? "text-xs font-semibold text-primary"
          : "text-[10px] text-muted-foreground",
      )}
    >
      {label}
    </span>
    {segment.topic ? (
      <Badge variant="outline" className={topicColorClass(segment.topic)}>
        {formatLabel(segment.topic)}
      </Badge>
    ) : (
      <Badge variant="outline" className="text-muted-foreground">
        No topic
      </Badge>
    )}
    {segment.subtopic && (
      <Badge variant="outline" className={SUBTOPIC_BADGE_CLASS}>
        {formatLabel(segment.subtopic)}
      </Badge>
    )}
    {segment.sentiment && (
      <Badge variant="outline" className={sentimentBadgeClass(segment.sentiment)}>
        {segment.sentiment}
      </Badge>
    )}
    <div
      className={cn("h-px flex-1", current ? "bg-primary/40" : "bg-border")}
    />
  </div>
);

interface ConversationStreamProps {
  view: ConversationView | null;
  loading: boolean;
  selectedSegmentId: number | null;
  onSelectSegment: (segment: SegmentSummary) => void;
  onReplaceBoundaries: (spans: { message_indices: number[] }[]) => void;
}

const ConversationStream = ({
  view,
  loading,
  selectedSegmentId,
  onSelectSegment,
  onReplaceBoundaries,
}: ConversationStreamProps) => {
  // Order segments into contiguous spans by their first message index.
  const orderedSegments = useMemo(() => {
    if (!view) return [];
    return [...view.segments].sort(
      (a, b) => (a.message_indices[0] ?? 0) - (b.message_indices[0] ?? 0),
    );
  }, [view]);

  const byIndex = useMemo(() => {
    const map = new Map<number, Message>();
    for (const m of view?.messages ?? []) map.set(m.index, m);
    return map;
  }, [view]);

  // Synthetic ingests (SuperDialseg) fabricate timestamps — either one uniform
  // time for the whole dialogue or epoch-era `1970-01-01 + Ns` sequences;
  // suppress the per-message time captions when either signature holds.
  const hideTimestamps = useMemo(
    () => hasSyntheticTimestamps((view?.messages ?? []).map((m) => m.createdAt)),
    [view],
  );

  // Frozen-boundary datasets (e.g. SuperDialseg gold): the gold segmentation is
  // authoritative, so the re-segmentation controls are hidden entirely while
  // segments stay selectable for naming.
  const frozen = view?.frozen_boundaries ?? false;

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Loading…
      </div>
    );
  }

  if (!view) {
    return (
      <EmptyState
        icon={MessagesSquare}
        title="Select a conversation"
        hint="Pick one from the queue to review its segments."
      />
    );
  }

  /** Split the span at `segIdx` into two at `splitIndex` (starts span 2). */
  const handleSplitHere = (segIdx: number, splitIndex: number) => {
    const spans = orderedSegments.map((s) => s.message_indices);
    onReplaceBoundaries(
      splitAt(spans, segIdx, splitIndex).map((message_indices) => ({
        message_indices,
      })),
    );
  };

  /** Merge the span at `segIdx` into the immediately-previous span. */
  const handleMergePrev = (segIdx: number) => {
    const spans = orderedSegments.map((s) => s.message_indices);
    onReplaceBoundaries(
      mergeWithPrevious(spans, segIdx).map((message_indices) => ({
        message_indices,
      })),
    );
  };

  return (
    <ScrollArea className="min-h-0 flex-1">
      <div className="flex flex-col gap-1 p-3">
        {orderedSegments.length === 0 && (
          <p className="py-8 text-center text-sm text-muted-foreground">
            No segments for this conversation
          </p>
        )}
        {orderedSegments.map((segment, segIdx) => {
          const isSelected = segment.id === selectedSegmentId;
          const messages = segment.message_indices
            .map((i) => byIndex.get(i))
            .filter((m): m is Message => Boolean(m));
          return (
            <div
              key={segment.id}
              onClick={() => onSelectSegment(segment)}
              className={cn(
                "cursor-pointer rounded-lg px-1 transition-colors",
                isSelected
                  ? "bg-accent ring-1 ring-primary/30"
                  : "hover:bg-accent/40",
              )}
            >
              <SegmentDivider
                label={isSelected ? "Selected" : `Segment ${segIdx + 1}`}
                segment={segment}
                current={isSelected}
                onMergePrev={
                  !frozen && segIdx > 0
                    ? () => handleMergePrev(segIdx)
                    : undefined
                }
              />
              <div className="flex flex-col gap-0.5 pb-2">
                {messages.length === 0 && (
                  <p className="text-center text-[10px] italic text-muted-foreground">
                    No messages
                  </p>
                )}
                {messages.map((msg, i) => (
                  <MessageBubble
                    key={msg.id}
                    msg={msg}
                    prevMsg={messages[i - 1]}
                    hideTimestamp={hideTimestamps}
                    onSplitHere={
                      !frozen && i > 0
                        ? () => handleSplitHere(segIdx, msg.index)
                        : undefined
                    }
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </ScrollArea>
  );
};

export default ConversationStream;
