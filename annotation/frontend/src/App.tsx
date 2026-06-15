import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Moon, Sun, Database } from "lucide-react";
import { toast } from "sonner";
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
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import SegmentQueue from "./components/SegmentQueue";
import SegmentMessages from "./components/SegmentMessages";
import StatisticsPanel from "./components/StatisticsPanel";
import AnnotationPanel from "./components/AnnotationPanel";
import SegmentFieldsPanel from "./components/SegmentFieldsPanel";

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
  return {
    theme,
    toggle: () => setTheme((t) => (t === "dark" ? "light" : "dark")),
  };
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

  const taxonomy = useMemo(
    () => buildTaxonomyMap(taxonomyEntries),
    [taxonomyEntries],
  );

  const fail = useCallback((e: unknown) => toast.error(String(e)), []);

  useEffect(() => {
    api
      .listDatasets()
      .then((names) => {
        setDatasets(names);
        if (names.length > 0) setDataset((cur) => cur || names[0]);
      })
      .catch(fail);
  }, [fail]);

  const refreshStats = useCallback(
    (ds: string) => {
      api.getStats(ds).then(setStats).catch(fail);
    },
    [fail],
  );

  const refreshQueue = useCallback(
    (ds: string, f: SegmentFilters) => {
      setQueueLoading(true);
      api
        .listSegments(ds, f)
        .then(setSegments)
        .catch(fail)
        .finally(() => setQueueLoading(false));
    },
    [fail],
  );

  useEffect(() => {
    if (!dataset) return;
    setSelectedId(null);
    setDetail(null);
    api.getTaxonomy(dataset).then(setTaxonomyEntries).catch(fail);
    refreshStats(dataset);
  }, [dataset, refreshStats, fail]);

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
        .catch(fail)
        .finally(() => setDetailLoading(false));
    },
    [dataset, fail],
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
        toast.success("Annotation saved");
        refreshQueue(dataset, filters);
        refreshStats(dataset);
        selectAdjacent(1);
      })
      .catch(fail)
      .finally(() => setSaving(false));
  }, [
    dataset,
    selectedId,
    topic,
    subtopic,
    reviewedBy,
    filters,
    refreshQueue,
    refreshStats,
    selectAdjacent,
    fail,
  ]);

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
        .then(() => {
          toast.success("Boundaries updated");
          afterWrite();
        })
        .catch(fail);
    },
    [dataset, detail, reviewedBy, afterWrite, fail],
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
      const el = e.target as HTMLElement | null;
      const tag = el?.tagName;
      const typing =
        tag === "INPUT" ||
        tag === "SELECT" ||
        tag === "TEXTAREA" ||
        el?.getAttribute("role") === "combobox" ||
        el?.closest("[data-radix-popper-content-wrapper]") != null;
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
    <TooltipProvider delayDuration={300}>
      <div className="flex h-full flex-col bg-muted text-foreground">
        <header className="flex items-center gap-3 border-b border-border bg-background px-4 py-2">
          <h1 className="text-sm font-semibold tracking-tight">
            UFL Annotation
          </h1>
          <div className="flex items-center gap-2">
            <Database className="size-4 text-muted-foreground" />
            <Select
              value={dataset}
              onValueChange={setDataset}
              disabled={datasets.length === 0}
            >
              <SelectTrigger size="sm" className="min-w-[180px]">
                <SelectValue placeholder="no datasets" />
              </SelectTrigger>
              <SelectContent>
                {datasets.map((d) => (
                  <SelectItem key={d} value={d}>
                    {d}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button
            variant="outline"
            size="icon-sm"
            onClick={toggle}
            title="Toggle theme"
            className="ml-auto"
          >
            {theme === "dark" ? (
              <Sun className="size-4" />
            ) : (
              <Moon className="size-4" />
            )}
          </Button>
        </header>

        <ResizablePanelGroup
          direction="horizontal"
          className="min-h-0 flex-1 gap-1.5 p-2"
        >
          <ResizablePanel defaultSize={22} minSize={15} maxSize={35}>
            <Card className="h-full gap-0 overflow-hidden py-0">
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
            </Card>
          </ResizablePanel>

          <ResizableHandle withHandle />

          <ResizablePanel defaultSize={50} minSize={30}>
            <Card className="flex h-full flex-col gap-0 overflow-hidden py-0">
              <SegmentMessages
                detail={detail}
                loading={detailLoading}
                onSelectSegment={loadSegment}
                onReplaceBoundaries={handleReplaceBoundaries}
              />
            </Card>
          </ResizablePanel>

          <ResizableHandle withHandle />

          <ResizablePanel defaultSize={28} minSize={18} maxSize={40}>
            <ResizablePanelGroup direction="vertical" className="gap-1.5">
              <ResizablePanel defaultSize={28} minSize={15}>
                <Card className="h-full gap-0 overflow-y-auto py-0">
                  <StatisticsPanel
                    stats={stats}
                    filters={filters}
                    taxonomy={taxonomy}
                    onFiltersChange={setFilters}
                  />
                </Card>
              </ResizablePanel>

              <ResizableHandle withHandle />

              <ResizablePanel defaultSize={36} minSize={20}>
                <Card className="flex h-full flex-col gap-0 overflow-hidden py-0">
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
                </Card>
              </ResizablePanel>

              <ResizableHandle withHandle />

              <ResizablePanel defaultSize={36} minSize={20}>
                <Card className="h-full gap-0 overflow-hidden py-0">
                  <SegmentFieldsPanel segment={detail?.segment ?? null} />
                </Card>
              </ResizablePanel>
            </ResizablePanelGroup>
          </ResizablePanel>
        </ResizablePanelGroup>
      </div>
      <Toaster theme={theme} position="bottom-right" />
    </TooltipProvider>
  );
}
