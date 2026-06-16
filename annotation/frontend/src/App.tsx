import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Moon,
  Sun,
  Database,
  LogOut,
  Redo2,
  Undo2,
  UserRound,
} from "lucide-react";
import { toast } from "sonner";
import { GoogleOAuthProvider } from "@react-oauth/google";
import {
  api,
  type BoundarySpan,
  type ConversationFilters,
  type ConversationSummary,
  type ConversationView,
  type SegmentSummary,
  type Stats,
  type TaxonomyEntry,
} from "./api";
import { buildTaxonomyMap } from "./lib/taxonomy";
import { useHistory } from "./lib/useHistory";
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
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import ConversationQueue from "./components/ConversationQueue";
import ConversationStream from "./components/ConversationStream";
import StatisticsPanel from "./components/StatisticsPanel";
import AnnotationPanel from "./components/AnnotationPanel";
import SegmentFieldsPanel from "./components/SegmentFieldsPanel";
import {
  AuthProvider,
  GOOGLE_CLIENT_ID,
  useAuth,
} from "./auth/AuthContext";
import SignInGate from "./auth/SignInGate";

const PAGE_SIZE = 50;

const LABELERS = ["labeler_a", "labeler_b"] as const;
type Labeler = (typeof LABELERS)[number];
const LABELER_KEY = "ufl.labeler";
// Radix Select forbids an empty-string item value, so the "no slot" option uses
// a sentinel that maps back to "" (unfiltered) at the boundary.
const NO_LABELER = "__all__";

function isLabeler(value: string | null): value is Labeler {
  return value === "labeler_a" || value === "labeler_b";
}

// Persisted labeler slot driving the per-labeler worklist filter (?labeler=).
// Empty string = no slot picked = unfiltered queue.
function useLabeler() {
  const [labeler, setLabelerState] = useState<Labeler | "">(() => {
    if (typeof window === "undefined") return "";
    const stored = window.localStorage.getItem(LABELER_KEY);
    return isLabeler(stored) ? stored : "";
  });
  const setLabeler = useCallback((next: Labeler | "") => {
    setLabelerState(next);
    if (typeof window === "undefined") return;
    if (next) window.localStorage.setItem(LABELER_KEY, next);
    else window.localStorage.removeItem(LABELER_KEY);
  }, []);
  return { labeler, setLabeler };
}

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

function AnnotationApp() {
  const { theme, toggle } = useTheme();
  const { ssoEnabled, user, signOut } = useAuth();
  const { labeler, setLabeler } = useLabeler();

  const [datasets, setDatasets] = useState<string[]>([]);
  const [dataset, setDataset] = useState("");

  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [filters, setFilters] = useState<ConversationFilters>({});
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [queueTotal, setQueueTotal] = useState(0);
  const [queueLoading, setQueueLoading] = useState(false);

  const [selectedConversation, setSelectedConversation] = useState<
    string | null
  >(null);
  const [view, setView] = useState<ConversationView | null>(null);
  const [viewLoading, setViewLoading] = useState(false);

  const [selectedSegment, setSelectedSegment] = useState<SegmentSummary | null>(
    null,
  );

  const [taxonomyEntries, setTaxonomyEntries] = useState<TaxonomyEntry[]>([]);
  const [usedTopics, setUsedTopics] = useState<string[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);

  const [topic, setTopic] = useState("");
  const [subtopic, setSubtopic] = useState("");
  const [manualReviewedBy, setManualReviewedBy] = useState("");
  const [saving, setSaving] = useState(false);

  // When SSO is on the server overrides reviewed_by with the verified Google
  // name; we mirror it read-only in the UI. When off, it's the manual input.
  const reviewedBy = ssoEnabled ? (user?.name ?? "") : manualReviewedBy;

  const history = useHistory();

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
    (
      ds: string,
      f: ConversationFilters,
      p: number,
      q: string,
      lab: Labeler | "",
    ) => {
      setQueueLoading(true);
      api
        .listConversations(ds, {
          ...f,
          page: p,
          pageSize: PAGE_SIZE,
          q: q || undefined,
          labeler: lab || undefined,
        })
        .then((res) => {
          setConversations(res.items);
          setQueueTotal(res.total);
        })
        .catch(fail)
        .finally(() => setQueueLoading(false));
    },
    [fail],
  );

  useEffect(() => {
    if (!dataset) return;
    setSelectedConversation(null);
    setView(null);
    setSelectedSegment(null);
    setFilters({});
    setSearch("");
    setPage(1);
    api.getTaxonomy(dataset).then(setTaxonomyEntries).catch(fail);
    api.usedTopics(dataset).then(setUsedTopics).catch(fail);
    refreshStats(dataset);
  }, [dataset, refreshStats, fail]);

  // A new filter or search resets to the first page; changing the page keeps
  // the current filter/search. Either way the queue refetches server-side.
  const setFiltersAndReset = useCallback((next: ConversationFilters) => {
    setFilters(next);
    setPage(1);
  }, []);

  const setSearchAndReset = useCallback((q: string) => {
    setSearch(q);
    setPage(1);
  }, []);

  // Picking/clearing a labeler is a new filter view: jump back to page 1 so the
  // queue shows that labeler's worklist from the top.
  useEffect(() => {
    setPage(1);
  }, [labeler]);

  useEffect(() => {
    if (!dataset) return;
    refreshQueue(dataset, filters, page, search, labeler);
  }, [dataset, filters, page, search, labeler, refreshQueue]);

  const selectSegment = useCallback((segment: SegmentSummary) => {
    setSelectedSegment(segment);
    setTopic(segment.topic ?? "");
    setSubtopic(segment.subtopic ?? "");
  }, []);

  const loadConversation = useCallback(
    (conversation: string) => {
      if (!dataset) return;
      setSelectedConversation(conversation);
      setViewLoading(true);
      api
        .getConversation(dataset, conversation)
        .then((v) => {
          setView(v);
          const first = [...v.segments].sort(
            (a, b) =>
              (a.message_indices[0] ?? 0) - (b.message_indices[0] ?? 0),
          )[0];
          if (first) {
            selectSegment(first);
          } else {
            setSelectedSegment(null);
          }
        })
        .catch(fail)
        .finally(() => setViewLoading(false));
    },
    [dataset, fail, selectSegment],
  );

  const selectAdjacentConversation = useCallback(
    (delta: number) => {
      if (conversations.length === 0) return;
      const idx = conversations.findIndex(
        (c) => c.conversation === selectedConversation,
      );
      const nextIdx =
        idx < 0
          ? 0
          : Math.min(Math.max(idx + delta, 0), conversations.length - 1);
      loadConversation(conversations[nextIdx].conversation);
    },
    [conversations, selectedConversation, loadConversation],
  );

  const afterWrite = useCallback(() => {
    if (!dataset) return;
    refreshQueue(dataset, filters, page, search, labeler);
    refreshStats(dataset);
    if (selectedConversation) loadConversation(selectedConversation);
  }, [
    dataset,
    filters,
    page,
    search,
    labeler,
    refreshQueue,
    refreshStats,
    selectedConversation,
    loadConversation,
  ]);

  // History closures re-fetch via the latest afterWrite/dataset snapshot.
  const afterWriteRef = useRef(afterWrite);
  const datasetRef = useRef(dataset);
  afterWriteRef.current = afterWrite;
  datasetRef.current = dataset;

  const handleSave = useCallback(() => {
    if (!dataset || !selectedSegment || topic.trim() === "") return;
    const segmentId = selectedSegment.id;
    const reviewer = reviewedBy || null;
    // Snapshot before-state BEFORE the write: the segment's current gold
    // (or null if it was unannotated).
    const before =
      selectedSegment.true_topic !== null
        ? {
            true_topic: selectedSegment.true_topic,
            true_subtopic: selectedSegment.true_subtopic ?? "",
          }
        : null;
    const after = { true_topic: topic, true_subtopic: subtopic };
    setSaving(true);
    api
      .annotate(dataset, segmentId, { ...after, reviewed_by: reviewer })
      .then(() => {
        toast.success("Annotation saved");
        history.push({
          label: "relabel",
          undo: async () => {
            const ds = datasetRef.current;
            if (before) {
              await api.annotate(ds, segmentId, {
                ...before,
                reviewed_by: reviewer,
              });
            } else {
              await api.clearAnnotation(ds, segmentId);
            }
            afterWriteRef.current();
          },
          redo: async () => {
            await api.annotate(datasetRef.current, segmentId, {
              ...after,
              reviewed_by: reviewer,
            });
            afterWriteRef.current();
          },
        });
        afterWrite();
      })
      .catch(fail)
      .finally(() => setSaving(false));
  }, [
    dataset,
    selectedSegment,
    topic,
    subtopic,
    reviewedBy,
    afterWrite,
    history,
    fail,
  ]);

  const handleConfirmAi = useCallback(() => {
    if (!selectedSegment) return;
    const aiTopic = selectedSegment.topic ?? "";
    const aiSubtopic = selectedSegment.subtopic ?? "";
    if (aiTopic === "") return;
    setTopic(aiTopic);
    setSubtopic(aiSubtopic);
  }, [selectedSegment]);

  const handleReplaceBoundaries = useCallback(
    (spans: BoundarySpan[]) => {
      if (!dataset || !selectedConversation || !view) return;
      const conversation = selectedConversation;
      const reviewer = reviewedBy || null;
      // Snapshot the conversation's CURRENT span set before the POST so undo
      // can restore the prior boundaries.
      const before: BoundarySpan[] = [...view.segments]
        .sort((a, b) => (a.message_indices[0] ?? 0) - (b.message_indices[0] ?? 0))
        .map((s) => ({
          message_indices: s.message_indices,
          topic: s.true_topic ?? s.topic,
          subtopic: s.true_subtopic ?? s.subtopic,
        }));
      const after = spans;
      const post = (segments: BoundarySpan[]) =>
        api.replaceBoundaries(datasetRef.current, conversation, {
          segments,
          reviewed_by: reviewer,
        });
      post(after)
        .then(() => {
          toast.success("Boundaries updated");
          history.push({
            label: "boundary",
            undo: async () => {
              await post(before);
              afterWriteRef.current();
            },
            redo: async () => {
              await post(after);
              afterWriteRef.current();
            },
          });
          afterWrite();
        })
        .catch(fail);
    },
    [dataset, selectedConversation, view, reviewedBy, afterWrite, history, fail],
  );

  // Keyboard orchestration (ignored while typing in inputs/selects).
  const saveRef = useRef(handleSave);
  const confirmRef = useRef(handleConfirmAi);
  const adjacentRef = useRef(selectAdjacentConversation);
  const undoRef = useRef(history.undo);
  const redoRef = useRef(history.redo);
  saveRef.current = handleSave;
  confirmRef.current = handleConfirmAi;
  adjacentRef.current = selectAdjacentConversation;
  undoRef.current = history.undo;
  redoRef.current = history.redo;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
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
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (e.shiftKey) {
          void redoRef.current();
        } else {
          void undoRef.current();
        }
        return;
      }
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
          <div className="flex items-center gap-2">
            <UserRound className="size-4 text-muted-foreground" />
            <Select
              value={labeler || NO_LABELER}
              onValueChange={(v) =>
                setLabeler(v === NO_LABELER ? "" : (v as Labeler))
              }
            >
              <SelectTrigger
                size="sm"
                className="min-w-[140px]"
                aria-label="Labeler"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_LABELER}>All labelers</SelectItem>
                {LABELERS.map((l) => (
                  <SelectItem key={l} value={l}>
                    {l}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="outline"
                  size="icon-sm"
                  onClick={() => void history.undo()}
                  disabled={!history.canUndo}
                  aria-label="Undo"
                >
                  <Undo2 className="size-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Undo (⌘/Ctrl+Z)</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="outline"
                  size="icon-sm"
                  onClick={() => void history.redo()}
                  disabled={!history.canRedo}
                  aria-label="Redo"
                >
                  <Redo2 className="size-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Redo (⌘/Ctrl+Shift+Z)</TooltipContent>
            </Tooltip>
            <Button
              variant="outline"
              size="icon-sm"
              onClick={toggle}
              title="Toggle theme"
            >
              {theme === "dark" ? (
                <Sun className="size-4" />
              ) : (
                <Moon className="size-4" />
              )}
            </Button>
            {ssoEnabled && user && (
              <div className="flex items-center gap-2 border-l border-border pl-2">
                {user.picture && (
                  <img
                    src={user.picture}
                    alt=""
                    className="size-6 rounded-full"
                  />
                )}
                <span className="text-xs font-medium" title={user.email}>
                  {user.name}
                </span>
                <Button
                  variant="outline"
                  size="icon-sm"
                  onClick={signOut}
                  title="Sign out"
                  aria-label="Sign out"
                >
                  <LogOut className="size-4" />
                </Button>
              </div>
            )}
          </div>
        </header>

        <ResizablePanelGroup
          direction="horizontal"
          className="min-h-0 flex-1 gap-1.5 p-2"
        >
          <ResizablePanel defaultSize={22} minSize={15} maxSize={35}>
            <Card className="h-full gap-0 overflow-hidden py-0">
              <ConversationQueue
                conversations={conversations}
                selectedConversation={selectedConversation}
                filters={filters}
                search={search}
                page={page}
                pageSize={PAGE_SIZE}
                total={queueTotal}
                taxonomy={taxonomy}
                loading={queueLoading}
                onSelect={loadConversation}
                onFiltersChange={setFiltersAndReset}
                onSearchChange={setSearchAndReset}
                onPageChange={setPage}
              />
            </Card>
          </ResizablePanel>

          <ResizableHandle withHandle />

          <ResizablePanel defaultSize={50} minSize={30}>
            <Card className="flex h-full flex-col gap-0 overflow-hidden py-0">
              <ConversationStream
                view={view}
                loading={viewLoading}
                selectedSegmentId={selectedSegment?.id ?? null}
                onSelectSegment={selectSegment}
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
                    onFiltersChange={setFiltersAndReset}
                  />
                </Card>
              </ResizablePanel>

              <ResizableHandle withHandle />

              <ResizablePanel defaultSize={36} minSize={20}>
                <Card className="flex h-full flex-col gap-0 overflow-hidden py-0">
                  <AnnotationPanel
                    segment={selectedSegment}
                    taxonomy={taxonomy}
                    usedTopics={usedTopics}
                    topic={topic}
                    subtopic={subtopic}
                    reviewedBy={reviewedBy}
                    reviewedByLocked={ssoEnabled}
                    saving={saving}
                    onTopicChange={(t) => {
                      setTopic(t);
                      setSubtopic("");
                    }}
                    onSubtopicChange={setSubtopic}
                    onReviewedByChange={setManualReviewedBy}
                    onConfirmAi={handleConfirmAi}
                    onSave={handleSave}
                    onPrev={() => selectAdjacentConversation(-1)}
                    onNext={() => selectAdjacentConversation(1)}
                  />
                </Card>
              </ResizablePanel>

              <ResizableHandle withHandle />

              <ResizablePanel defaultSize={36} minSize={20}>
                <Card className="h-full gap-0 overflow-hidden py-0">
                  <SegmentFieldsPanel segment={selectedSegment} />
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

function GatedApp() {
  return (
    <SignInGate>
      <AnnotationApp />
    </SignInGate>
  );
}

export default function App() {
  if (GOOGLE_CLIENT_ID) {
    return (
      <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
        <AuthProvider>
          <GatedApp />
        </AuthProvider>
      </GoogleOAuthProvider>
    );
  }
  return (
    <AuthProvider>
      <AnnotationApp />
    </AuthProvider>
  );
}
