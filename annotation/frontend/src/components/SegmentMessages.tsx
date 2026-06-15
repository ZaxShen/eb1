import { useMemo } from "react";
import { ArrowUpToLine, Scissors } from "lucide-react";
import type { Message, SegmentDetail, SegmentSummary } from "../api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { topicColorClass, SUBTOPIC_BADGE_CLASS } from "../lib/badges";
import {
  cn,
  formatChatTimestamp,
  formatLabel,
  isSameMinute,
} from "../lib/utils";

// Bubble color-by-role, mirroring ufl-dev RoleStyleLight/Dark via semantic
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
  muted,
  onSplitHere,
}: {
  msg: Message;
  prevMsg?: Message;
  muted?: boolean;
  onSplitHere?: () => void;
}) => {
  const isUser = isUserRole(msg.type);
  const bubbleStyle = roleStyle(msg.type);
  const isFirstInSeries = !prevMsg || prevMsg.type !== msg.type;
  const showTimestamp =
    isFirstInSeries || !isSameMinute(prevMsg?.createdAt, msg.createdAt);

  return (
    <div
      className={cn(
        "group flex flex-col gap-0.5",
        isUser ? "items-start" : "items-end",
        muted && "opacity-60",
      )}
    >
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
          "flex items-end gap-1",
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
                onClick={onSplitHere}
                className="shrink-0 opacity-0 transition-opacity group-hover:opacity-100"
              >
                <Scissors />
              </Button>
            </TooltipTrigger>
            <TooltipContent>
              Split a new segment starting here
            </TooltipContent>
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
            onClick={onMergePrev}
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
      <Badge variant="outline" className="text-muted-foreground">
        {segment.sentiment}
      </Badge>
    )}
    <div
      className={cn("h-px flex-1", current ? "bg-primary/40" : "bg-border")}
    />
  </div>
);

interface SegmentMessagesProps {
  detail: SegmentDetail | null;
  loading: boolean;
  onSelectSegment: (segmentId: number) => void;
  onReplaceBoundaries: (spans: { message_indices: number[] }[]) => void;
}

const SegmentMessages = ({
  detail,
  loading,
  onSelectSegment,
  onReplaceBoundaries,
}: SegmentMessagesProps) => {
  // Order siblings into contiguous spans by their first message index.
  const orderedSpans = useMemo(() => {
    if (!detail) return [];
    return [...detail.siblings].sort(
      (a, b) => (a.message_indices[0] ?? 0) - (b.message_indices[0] ?? 0),
    );
  }, [detail]);

  const byIndex = useMemo(() => {
    const map = new Map<number, Message>();
    for (const m of detail?.messages ?? []) map.set(m.index, m);
    return map;
  }, [detail]);

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Loading…
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Select a segment
      </div>
    );
  }

  const currentId = detail.segment.id;

  /** Split the current span into two at `splitIndex` (which starts span 2). */
  const handleSplitHere = (splitIndex: number) => {
    const newSpans = orderedSpans.map((span) => {
      if (span.id !== currentId) {
        return { message_indices: span.message_indices };
      }
      const before = span.message_indices.filter((i) => i < splitIndex);
      const after = span.message_indices.filter((i) => i >= splitIndex);
      return [before, after];
    });
    const flattened: { message_indices: number[] }[] = [];
    for (const entry of newSpans) {
      if (Array.isArray(entry)) {
        for (const part of entry) {
          if (part.length > 0) flattened.push({ message_indices: part });
        }
      } else {
        flattened.push(entry);
      }
    }
    onReplaceBoundaries(flattened);
  };

  /** Merge the current span into the immediately-previous span. */
  const handleMergePrev = () => {
    const currentPos = orderedSpans.findIndex((s) => s.id === currentId);
    if (currentPos <= 0) return;
    const spans: { message_indices: number[] }[] = [];
    for (let i = 0; i < orderedSpans.length; i += 1) {
      if (i === currentPos) continue;
      if (i === currentPos - 1) {
        spans.push({
          message_indices: [
            ...orderedSpans[i].message_indices,
            ...orderedSpans[currentPos].message_indices,
          ].sort((a, b) => a - b),
        });
      } else {
        spans.push({ message_indices: orderedSpans[i].message_indices });
      }
    }
    onReplaceBoundaries(spans);
  };

  return (
    <ScrollArea className="min-h-0 flex-1">
      <div className="flex flex-col gap-1 p-3">
        {orderedSpans.map((span, spanIdx) => {
          const isCurrent = span.id === currentId;
          const messages = span.message_indices
            .map((i) => byIndex.get(i))
            .filter((m): m is Message => Boolean(m));
          return (
            <div key={span.id} className={cn(!isCurrent && "opacity-70")}>
              {isCurrent ? (
                <SegmentDivider
                  label="Current"
                  segment={span}
                  current
                  onMergePrev={spanIdx > 0 ? handleMergePrev : undefined}
                />
              ) : (
                <button
                  onClick={() => onSelectSegment(span.id)}
                  className="w-full transition-opacity hover:opacity-100"
                >
                  <SegmentDivider label="Context" segment={span} />
                </button>
              )}
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
                    muted={!isCurrent}
                    onSplitHere={
                      isCurrent && i > 0
                        ? () => handleSplitHere(msg.index)
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

export default SegmentMessages;
