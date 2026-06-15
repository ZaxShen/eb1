import { useMemo } from "react";
import type {
  BoundarySpan,
  ConversationView as ConversationData,
  SegmentSummary,
} from "../api";

interface ConversationViewProps {
  conversation: ConversationData | null;
  selectedSegmentId: number | null;
  savingBoundaries: boolean;
  onSelectSegment: (segmentId: number) => void;
  onReplaceBoundaries: (spans: BoundarySpan[]) => void;
}

interface Span {
  indices: number[];
  topic: string | null;
  subtopic: string | null;
  sentiment: string | null;
}

function segmentToSpan(seg: SegmentSummary): Span {
  return {
    indices: [...seg.message_indices].sort((a, b) => a - b),
    topic: seg.topic,
    subtopic: seg.subtopic,
    sentiment: seg.sentiment,
  };
}

// Current spans for the conversation: prefer human gold if present,
// otherwise the machine segments, ordered by first message index.
function currentSpans(conv: ConversationData): Span[] {
  const source: Span[] =
    conv.gold_segments.length > 0
      ? conv.gold_segments.map((g) => ({
          indices: [...g.message_indices].sort((a, b) => a - b),
          topic: g.topic,
          subtopic: g.subtopic,
          sentiment: g.sentiment,
        }))
      : conv.segments.map(segmentToSpan);
  return source
    .filter((s) => s.indices.length > 0)
    .sort((a, b) => a.indices[0] - b.indices[0]);
}

function toBoundarySpans(spans: Span[]): BoundarySpan[] {
  return spans.map((s) => ({
    message_indices: s.indices,
    topic: s.topic,
    subtopic: s.subtopic,
    sentiment: s.sentiment,
  }));
}

export default function ConversationView({
  conversation,
  selectedSegmentId,
  savingBoundaries,
  onSelectSegment,
  onReplaceBoundaries,
}: ConversationViewProps) {
  const spans = useMemo(
    () => (conversation ? currentSpans(conversation) : []),
    [conversation],
  );

  const indexToSpan = useMemo(() => {
    const map = new Map<number, number>();
    spans.forEach((span, i) => {
      for (const idx of span.indices) map.set(idx, i);
    });
    return map;
  }, [spans]);

  const selectedSpanIndex = useMemo(() => {
    if (!conversation || selectedSegmentId == null) return null;
    const seg = conversation.segments.find((s) => s.id === selectedSegmentId);
    if (!seg) return null;
    const first = [...seg.message_indices].sort((a, b) => a - b)[0];
    return first != null ? (indexToSpan.get(first) ?? null) : null;
  }, [conversation, selectedSegmentId, indexToSpan]);

  if (!conversation) {
    return (
      <div className="p-4 text-sm text-slate-400">
        Select a segment to view its conversation.
      </div>
    );
  }

  const splitAt = (messageIndex: number) => {
    const spanIdx = indexToSpan.get(messageIndex);
    if (spanIdx == null) return;
    const span = spans[spanIdx];
    const pos = span.indices.indexOf(messageIndex);
    // Split so that the chosen message starts a new span. No-op if it is
    // already the first message of the span (nothing before it to split).
    if (pos <= 0) return;
    const left = { ...span, indices: span.indices.slice(0, pos) };
    const right = { ...span, indices: span.indices.slice(pos) };
    const next = [...spans.slice(0, spanIdx), left, right, ...spans.slice(spanIdx + 1)];
    onReplaceBoundaries(toBoundarySpans(next));
  };

  const mergeWithNext = (spanIdx: number) => {
    if (spanIdx >= spans.length - 1) return;
    const merged: Span = {
      ...spans[spanIdx],
      indices: [...spans[spanIdx].indices, ...spans[spanIdx + 1].indices].sort(
        (a, b) => a - b,
      ),
    };
    const next = [
      ...spans.slice(0, spanIdx),
      merged,
      ...spans.slice(spanIdx + 2),
    ];
    onReplaceBoundaries(toBoundarySpans(next));
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2">
        <div className="text-sm font-medium text-slate-700">
          {conversation.conversation}
        </div>
        <div className="text-xs text-slate-400">
          {spans.length} span{spans.length === 1 ? "" : "s"}
          {savingBoundaries && (
            <span className="ml-2 text-blue-500">saving…</span>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {conversation.messages.map((msg, i) => {
          const spanIdx = indexToSpan.get(msg.index);
          const inSelected =
            selectedSpanIndex != null && spanIdx === selectedSpanIndex;
          const prevSpanIdx =
            i > 0 ? indexToSpan.get(conversation.messages[i - 1].index) : undefined;
          const isSpanStart = spanIdx != null && spanIdx !== prevSpanIdx;

          return (
            <div key={msg.index}>
              {isSpanStart && (
                <div className="mb-1 mt-3 flex items-center gap-2 text-xs">
                  <span className="font-semibold text-slate-500">
                    Span {spanIdx + 1}
                    {spans[spanIdx].topic ? ` · ${spans[spanIdx].topic}` : ""}
                  </span>
                  {spanIdx > 0 && (
                    <button
                      type="button"
                      onClick={() => mergeWithNext(spanIdx - 1)}
                      disabled={savingBoundaries}
                      className="rounded border border-slate-300 px-1.5 py-0.5 text-slate-500 hover:bg-slate-100 disabled:opacity-50"
                      title="Merge this span with the previous one"
                    >
                      ⬆ merge prev
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => splitAt(msg.index)}
                    disabled={savingBoundaries}
                    className="rounded border border-slate-300 px-1.5 py-0.5 text-slate-500 hover:bg-slate-100 disabled:opacity-50"
                    title="Split so this message starts a new span"
                  >
                    ✂ split here
                  </button>
                </div>
              )}
              <button
                type="button"
                onClick={() => {
                  if (spanIdx == null) return;
                  const seg = conversation.segments.find((s) =>
                    s.message_indices.includes(msg.index),
                  );
                  if (seg) onSelectSegment(seg.id);
                }}
                className={`mb-1 block w-full rounded border px-3 py-2 text-left text-sm ${
                  inSelected
                    ? "border-blue-300 bg-blue-50"
                    : "border-slate-200 bg-white hover:bg-slate-50"
                }`}
              >
                <div className="mb-0.5 flex items-center gap-2 text-xs text-slate-400">
                  <span className="font-medium uppercase">{msg.type}</span>
                  <span>#{msg.index}</span>
                </div>
                <div className="whitespace-pre-wrap text-slate-700">
                  {msg.message}
                </div>
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
