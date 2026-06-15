import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import {
  api,
  type BoundarySpan,
  type SegmentDetail,
  type SegmentFilters,
  type SegmentSummary,
  type Stats,
  type TaxonomyEntry,
} from "./api";
import { buildTaxonomyMap } from "./lib/taxonomy";
import SegmentQueue from "./components/SegmentQueue";
import SegmentMessages from "./components/SegmentMessages";
import StatisticsPanel from "./components/StatisticsPanel";
import AnnotationPanel from "./components/AnnotationPanel";
import SegmentFieldsPanel from "./components/SegmentFieldsPanel";

const CARD = "h-full overflow-hidden rounded-xl border border-border/50 bg-background shadow-lg";

function useTheme() {
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    if (typeof window === "undefined") return "dark";
    return window.matchMedia?.("(prefers-color-scheme: light)").matches
      ? "light"
      : "dark";
  });
  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);
  return { theme, toggle: () => setTheme((t) => (t === "dark" ? "light" : "dark")) };
}

export default function App() {
  const { theme, toggle } = useTheme();

  const [datasets, setDatasets] = useState<string[]>([]);
  const [dataset, setDataset] = useState("");

  const [segments, setSegments] = useState<SegmentSummary[]>([]);
  const [filters, setFilters] = useState<SegmentFilters>({});
  const [queueLoading, setQueueLoading] = useState(false);

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<SegmentDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const [taxonomyEntries, setTaxonomyEntries] = useState<TaxonomyEntry[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);

  const [topic, setTopic] = useState("");
  const [subtopic, setSubtopic] = useState("");
  const [reviewedBy, setReviewedBy] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const taxonomy = useMemo(() => buildTaxonomyMap(taxonomyEntries), [taxonomyEntries]);

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
    api.getStats(ds).then(setStats).catch((e: unknown) => setError(String(e)));
  }, []);

  const refreshQueue = useCallback((ds: string, f: SegmentFilters) => {
    setQueueLoading(true);
    api
      .listSegments(ds, f)
      .then(setSegments)
      .catch((e: unknown) => setError(String(e)))
      .finally(() => setQueueLoading(false));
  }, []);

  useEffect(() => {
    if (!dataset) return;
    setSelectedId(null);
    setDetail(null);
    api
      .getTaxonomy(dataset)
      .then(setTaxonomyEntries)
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
      setDetailLoading(true);
      api
        .getSegment(dataset, segmentId)
        .then((d) => {
          setDetail(d);
          setTopic(d.segment.topic ?? "");
          setSubtopic(d.segment.subtopic ?? "");
        })
        .catch((e: unknown) => setError(String(e)))
        .finally(() => setDetailLoading(false));
    },
    [dataset],
  );

  const selectAdjacent = useCallback(
    (delta: number) => {
      if (segments.length === 0) return;
      const idx = segments.findIndex((s) => s.id === selectedId);
      const nextIdx =
        idx < 0 ? 0 : Math.min(Math.max(idx + delta, 0), segments.length - 1);
      loadSegment(segments[nextIdx].id);
    },
    [segments, selectedId, loadSegment],
  );

  const afterWrite = useCallback(() => {
    if (!dataset) return;
    refreshQueue(dataset, filters);
    refreshStats(dataset);
    if (selectedId != null) loadSegment(selectedId);
  }, [dataset, filters, refreshQueue, refreshStats, selectedId, loadSegment]);

  const handleSave = useCallback(() => {
    if (!dataset || selectedId == null || topic.trim() === "") return;
    setSaving(true);
    api
      .annotate(dataset, selectedId, {
        true_topic: topic,
        true_subtopic: subtopic,
        reviewed_by: reviewedBy || null,
      })
      .then(() => {
        refreshQueue(dataset, filters);
        refreshStats(dataset);
        selectAdjacent(1);
      })
      .catch((e: unknown) => setError(String(e)))
      .finally(() => setSaving(false));
  }, [dataset, selectedId, topic, subtopic, reviewedBy, filters, refreshQueue, refreshStats, selectAdjacent]);

  const handleConfirmAi = useCallback(() => {
    if (!detail) return;
    const aiTopic = detail.segment.topic ?? "";
    const aiSubtopic = detail.segment.subtopic ?? "";
    if (aiTopic === "") return;
    setTopic(aiTopic);
    setSubtopic(aiSubtopic);
  }, [detail]);

  const handleReplaceBoundaries = useCallback(
    (spans: BoundarySpan[]) => {
      if (!dataset || !detail) return;
      api
        .replaceBoundaries(dataset, detail.segment.conversation, {
          segments: spans,
          reviewed_by: reviewedBy || null,
        })
        .then(() => afterWrite())
        .catch((e: unknown) => setError(String(e)));
    },
    [dataset, detail, reviewedBy, afterWrite],
  );

  // Keyboard orchestration (ignored while typing in inputs/selects).
  const saveRef = useRef(handleSave);
  const confirmRef = useRef(handleConfirmAi);
  const adjacentRef = useRef(selectAdjacent);
  saveRef.current = handleSave;
  confirmRef.current = handleConfirmAi;
  adjacentRef.current = selectAdjacent;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      const typing = tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA";
      if (typing) return;
      if (e.key === "Enter") {
        e.preventDefault();
        saveRef.current();
      } else if (e.key === " ") {
        e.preventDefault();
        confirmRef.current();
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        adjacentRef.current(-1);
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        adjacentRef.current(1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="flex h-full flex-col bg-muted text-foreground">
      <header className="flex items-center gap-3 px-3 py-2">
        <h1 className="text-sm font-semibold">UFL Annotation</h1>
        <div className="flex items-center gap-1.5 rounded-md border border-border bg-background px-2">
          <span className="text-[11px] text-muted-foreground">dataset</span>
          <select
            value={dataset}
            onChange={(e) => setDataset(e.target.value)}
            className="bg-transparent py-1 text-sm focus:outline-none"
          >
            {datasets.length === 0 && <option value="">no datasets</option>}
            {datasets.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </div>
        <button
          onClick={toggle}
          className="ml-auto rounded-md border border-border bg-background px-2 py-1 text-xs hover:bg-secondary/60"
          title="Toggle theme"
        >
          {theme === "dark" ? "Light" : "Dark"}
        </button>
        {error && (
          <button
            type="button"
            onClick={() => setError(null)}
            className="rounded-md bg-red-500/10 px-2 py-1 text-xs text-red-500"
            title="Dismiss"
          >
            {error}
          </button>
        )}
      </header>

      <PanelGroup direction="horizontal" className="min-h-0 flex-1 gap-1 px-2 pb-2">
        <Panel defaultSize={22} minSize={15} maxSize={35}>
          <div className={CARD}>
            <SegmentQueue
              segments={segments}
              selectedId={selectedId}
              filters={filters}
              taxonomy={taxonomy}
              loading={queueLoading}
              total={stats?.total ?? segments.length}
              onSelect={loadSegment}
              onFiltersChange={setFilters}
            />
          </div>
        </Panel>

        <PanelResizeHandle className="w-1" />

        <Panel defaultSize={50} minSize={30}>
          <div className={`${CARD} flex flex-col`}>
            <SegmentMessages
              detail={detail}
              loading={detailLoading}
              onSelectSegment={loadSegment}
              onReplaceBoundaries={handleReplaceBoundaries}
            />
          </div>
        </Panel>

        <PanelResizeHandle className="w-1" />

        <Panel defaultSize={28} minSize={18} maxSize={40}>
          <PanelGroup direction="vertical" className="h-full gap-1">
            <Panel defaultSize={28} minSize={15}>
              <div className={`${CARD} overflow-y-auto`}>
                <StatisticsPanel
                  stats={stats}
                  filters={filters}
                  taxonomy={taxonomy}
                  onFiltersChange={setFilters}
                />
              </div>
            </Panel>

            <PanelResizeHandle className="h-1" />

            <Panel defaultSize={32} minSize={20}>
              <div className={`${CARD} flex flex-col`}>
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
                  onConfirmAi={handleConfirmAi}
                  onSave={handleSave}
                  onPrev={() => selectAdjacent(-1)}
                  onNext={() => selectAdjacent(1)}
                />
              </div>
            </Panel>

            <PanelResizeHandle className="h-1" />

            <Panel defaultSize={60} minSize={20}>
              <div className={CARD}>
                <SegmentFieldsPanel segment={detail?.segment ?? null} />
              </div>
            </Panel>
          </PanelGroup>
        </Panel>
      </PanelGroup>
    </div>
  );
}
