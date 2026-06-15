import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  type BoundarySpan,
  type ConversationView as ConversationData,
  type SegmentDetail,
  type SegmentFilters,
  type SegmentSummary,
  type Stats,
  type TaxonomyEntry,
} from "./api";
import SegmentQueue from "./components/SegmentQueue";
import ConversationView from "./components/ConversationView";
import AnnotationPanel from "./components/AnnotationPanel";
import StatsBar from "./components/StatsBar";

export default function App() {
  const [datasets, setDatasets] = useState<string[]>([]);
  const [dataset, setDataset] = useState<string>("");

  const [segments, setSegments] = useState<SegmentSummary[]>([]);
  const [filters, setFilters] = useState<SegmentFilters>({});
  const [queueLoading, setQueueLoading] = useState(false);

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<SegmentDetail | null>(null);
  const [conversation, setConversation] = useState<ConversationData | null>(
    null,
  );

  const [taxonomy, setTaxonomy] = useState<TaxonomyEntry[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);

  const [topic, setTopic] = useState("");
  const [subtopic, setSubtopic] = useState("");
  const [reviewedBy, setReviewedBy] = useState("");
  const [saving, setSaving] = useState(false);
  const [savingBoundaries, setSavingBoundaries] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const topicOptions = useMemo(() => {
    const seen = new Set<string>();
    for (const s of segments) if (s.topic) seen.add(s.topic);
    return [...seen].sort();
  }, [segments]);

  useEffect(() => {
    api
      .listDatasets()
      .then((names) => {
        setDatasets(names);
        if (names.length > 0) setDataset((cur) => cur || names[0]);
      })
      .catch((e: unknown) => setError(String(e)));
  }, []);

  const refreshStats = useCallback((ds: string) => {
    api
      .getStats(ds)
      .then(setStats)
      .catch((e: unknown) => setError(String(e)));
  }, []);

  const refreshQueue = useCallback(
    (ds: string, f: SegmentFilters) => {
      setQueueLoading(true);
      api
        .listSegments(ds, f)
        .then(setSegments)
        .catch((e: unknown) => setError(String(e)))
        .finally(() => setQueueLoading(false));
    },
    [],
  );

  useEffect(() => {
    if (!dataset) return;
    setSelectedId(null);
    setDetail(null);
    setConversation(null);
    api
      .getTaxonomy(dataset)
      .then(setTaxonomy)
      .catch((e: unknown) => setError(String(e)));
    refreshStats(dataset);
  }, [dataset, refreshStats]);

  useEffect(() => {
    if (!dataset) return;
    refreshQueue(dataset, filters);
  }, [dataset, filters, refreshQueue]);

  const loadSegment = useCallback(
    (segmentId: number) => {
      if (!dataset) return;
      setSelectedId(segmentId);
      api
        .getSegment(dataset, segmentId)
        .then((d) => {
          setDetail(d);
          setTopic(d.segment.topic ?? "");
          setSubtopic(d.segment.subtopic ?? "");
          return api.getConversation(dataset, d.segment.conversation);
        })
        .then(setConversation)
        .catch((e: unknown) => setError(String(e)));
    },
    [dataset],
  );

  const selectAdjacent = useCallback(
    (delta: number) => {
      if (segments.length === 0) return;
      const idx = segments.findIndex((s) => s.id === selectedId);
      const nextIdx =
        idx < 0
          ? 0
          : Math.min(Math.max(idx + delta, 0), segments.length - 1);
      loadSegment(segments[nextIdx].id);
    },
    [segments, selectedId, loadSegment],
  );

  const afterWrite = useCallback(() => {
    if (!dataset) return;
    refreshQueue(dataset, filters);
    refreshStats(dataset);
  }, [dataset, filters, refreshQueue, refreshStats]);

  const handleSave = useCallback(() => {
    if (!dataset || selectedId == null) return;
    if (topic.trim() === "" || subtopic.trim() === "") return;
    setSaving(true);
    api
      .annotate(dataset, selectedId, {
        true_topic: topic,
        true_subtopic: subtopic,
        reviewed_by: reviewedBy || null,
      })
      .then(() => afterWrite())
      .catch((e: unknown) => setError(String(e)))
      .finally(() => setSaving(false));
  }, [dataset, selectedId, topic, subtopic, reviewedBy, afterWrite]);

  const handleConfirmAi = useCallback(() => {
    if (!detail) return;
    const aiTopic = detail.segment.topic ?? "";
    const aiSubtopic = detail.segment.subtopic ?? "";
    if (aiTopic === "" || aiSubtopic === "" || !dataset || selectedId == null)
      return;
    setTopic(aiTopic);
    setSubtopic(aiSubtopic);
    setSaving(true);
    api
      .annotate(dataset, selectedId, {
        true_topic: aiTopic,
        true_subtopic: aiSubtopic,
        reviewed_by: reviewedBy || null,
      })
      .then(() => afterWrite())
      .catch((e: unknown) => setError(String(e)))
      .finally(() => setSaving(false));
  }, [detail, dataset, selectedId, reviewedBy, afterWrite]);

  const handleReplaceBoundaries = useCallback(
    (spans: BoundarySpan[]) => {
      if (!dataset || !conversation) return;
      setSavingBoundaries(true);
      api
        .replaceBoundaries(dataset, conversation.conversation, {
          segments: spans,
          reviewed_by: reviewedBy || null,
        })
        .then(() => api.getConversation(dataset, conversation.conversation))
        .then((c) => {
          setConversation(c);
          afterWrite();
        })
        .catch((e: unknown) => setError(String(e)))
        .finally(() => setSavingBoundaries(false));
    },
    [dataset, conversation, reviewedBy, afterWrite],
  );

  const saveRef = useRef(handleSave);
  const confirmRef = useRef(handleConfirmAi);
  const adjacentRef = useRef(selectAdjacent);
  saveRef.current = handleSave;
  confirmRef.current = handleConfirmAi;
  adjacentRef.current = selectAdjacent;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const tag = target?.tagName;
      const typing =
        tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA";
      if (e.key === "Enter" && !typing) {
        e.preventDefault();
        saveRef.current();
      } else if (e.key === " " && !typing) {
        e.preventDefault();
        confirmRef.current();
      } else if (e.key === "ArrowLeft" && !typing) {
        e.preventDefault();
        adjacentRef.current(-1);
      } else if (e.key === "ArrowRight" && !typing) {
        e.preventDefault();
        adjacentRef.current(1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="flex h-full flex-col bg-white text-slate-900">
      <header className="flex items-center gap-3 border-b border-slate-200 px-4 py-2">
        <h1 className="text-sm font-semibold text-slate-700">
          UFL Annotation
        </h1>
        <select
          className="rounded border border-slate-300 px-2 py-1 text-sm"
          value={dataset}
          onChange={(e) => setDataset(e.target.value)}
        >
          {datasets.length === 0 && <option value="">no datasets</option>}
          {datasets.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
        {error && (
          <button
            type="button"
            onClick={() => setError(null)}
            className="ml-auto rounded bg-red-50 px-2 py-1 text-xs text-red-600"
            title="Dismiss"
          >
            {error}
          </button>
        )}
      </header>

      <StatsBar stats={stats} />

      <div className="grid min-h-0 flex-1 grid-cols-[20rem_1fr_22rem]">
        <aside className="min-h-0 border-r border-slate-200">
          <SegmentQueue
            segments={segments}
            selectedId={selectedId}
            filters={filters}
            topics={topicOptions}
            loading={queueLoading}
            onSelect={loadSegment}
            onFiltersChange={setFilters}
          />
        </aside>

        <main className="min-h-0 border-r border-slate-200">
          <ConversationView
            conversation={conversation}
            selectedSegmentId={selectedId}
            savingBoundaries={savingBoundaries}
            onSelectSegment={loadSegment}
            onReplaceBoundaries={handleReplaceBoundaries}
          />
        </main>

        <aside className="min-h-0">
          <AnnotationPanel
            detail={detail}
            taxonomy={taxonomy}
            topic={topic}
            subtopic={subtopic}
            reviewedBy={reviewedBy}
            saving={saving}
            onTopicChange={(t) => {
              setTopic(t);
              setSubtopic("");
            }}
            onSubtopicChange={setSubtopic}
            onReviewedByChange={setReviewedBy}
            onSave={handleSave}
            onConfirmAi={handleConfirmAi}
          />
        </aside>
      </div>
    </div>
  );
}
