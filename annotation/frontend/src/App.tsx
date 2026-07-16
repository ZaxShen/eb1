import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Moon,
  Sun,
  Database,
  LogOut,
  Redo2,
  Undo2,
  UserRound,
  Tags,
} from "lucide-react";
import { toast } from "sonner";
import { GoogleOAuthProvider } from "@react-oauth/google";
import {
  api,
  type BertopicLabels,
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
import TaxonomyManager from "./components/TaxonomyManager";
import {
  AuthProvider,
  GOOGLE_CLIENT_ID,
  useAuth,
} from "./auth/AuthContext";
import SignInGate from "./auth/SignInGate";

const PAGE_SIZE = 50;

const LABELER_KEY = "eb1.labeler";
// Radix Select forbids an empty-string item value, so the "All labelers" option
// uses a sentinel that maps back to "" (unfiltered) at the boundary. Persisting
// the sentinel also records an EXPLICIT "All" choice, distinct from "never set".
const NO_LABELER = "__all__";

// Resolve the effective labeler filter for a dataset from its fetched labelers,
// the persisted selection, and the signed-in identity. Precedence: an explicit
// "All" choice is kept; else a persisted labeler still present in the list is
// kept; else the signed-in email defaults it when the list contains it; else
// "All" (unfiltered). Stale persisted values fall through to the default.
function resolveLabeler(
  list: string[],
  stored: string | null,
  email: string | undefined,
): string {
  if (stored === NO_LABELER) return "";
  if (stored && list.includes(stored)) return stored;
  if (email && list.includes(email)) return email;
  return "";
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

  const [datasets, setDatasets] = useState<string[]>([]);
  const [dataset, setDataset] = useState("");

  // Per-dataset worklist labelers driving the identity-bound filter. `labeler`
  // is the active selection ("" = All / unfiltered); `labelers` is the fetched
  // list — empty hides the Select entirely.
  const [labelers, setLabelers] = useState<string[]>([]);
  const [labeler, setLabeler] = useState("");
  // Which dataset the labelers query has settled for. The queue fetch is gated
  // on this matching the active dataset, so a premature unfiltered request can't
  // race (and lose to) the post-resolution filtered one on mount or a switch.
  const [labelersReadyFor, setLabelersReadyFor] = useState<string | null>(null);

  const applyLabeler = useCallback((next: string) => {
    setLabeler(next);
    if (typeof window === "undefined") return;
    window.localStorage.setItem(LABELER_KEY, next || NO_LABELER);
  }, []);

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
  const [bertopicLabels, setBertopicLabels] = useState<BertopicLabels>({
    topics: [],
    subtopics: [],
  });
  const [stats, setStats] = useState<Stats | null>(null);
  const [taxonomyManagerOpen, setTaxonomyManagerOpen] = useState(false);

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

  // The annotator only ever picks within the conversation's KNOWN domain, so the
  // True Topic/Subtopic options are the domain-scoped slice of the taxonomy (a
  // dataset with no domains — null — shows the whole taxonomy unchanged).
  const conversationDomain = view?.domain ?? null;
  const annotationTaxonomy = useMemo(
    () =>
      buildTaxonomyMap(
        conversationDomain
          ? taxonomyEntries.filter((e) => e.domain === conversationDomain)
          : taxonomyEntries,
      ),
    [taxonomyEntries, conversationDomain],
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

  // Refetch taxonomy + used-topics together so the annotation dropdowns reflect a
  // taxonomy edit (add/rename/merge/delete) immediately. Returns a promise the
  // manager + dropdown add-new flow await before re-rendering.
  const refreshTaxonomy = useCallback(
    (ds: string) =>
      Promise.all([
        api.getTaxonomy(ds).then(setTaxonomyEntries),
        api.usedTopics(ds).then(setUsedTopics),
      ]).then(
        () => undefined,
        (e) => {
          fail(e);
        },
      ),
    [fail],
  );

  // Source topic/subtopic filter options for the queue, refreshed per dataset.
  const refreshBertopicLabels = useCallback(
    (ds: string) => {
      api
        .bertopicLabels(ds)
        .then(setBertopicLabels)
        .catch(() => setBertopicLabels({ topics: [], subtopics: [] }));
    },
    [],
  );

  // Worklist labelers for the dataset, refreshed per dataset. Resolves the active
  // filter against the persisted selection + signed-in identity (see
  // resolveLabeler) and persists the resolution so it survives a reload.
  const refreshLabelers = useCallback(
    (ds: string) => {
      api
        .labelers(ds)
        .then((list) => {
          setLabelers(list);
          const stored =
            typeof window !== "undefined"
              ? window.localStorage.getItem(LABELER_KEY)
              : null;
          applyLabeler(resolveLabeler(list, stored, user?.email));
          setLabelersReadyFor(ds);
        })
        .catch(() => {
          setLabelers([]);
          setLabeler("");
          setLabelersReadyFor(ds);
        });
    },
    [applyLabeler, user?.email],
  );

  // Monotonic id stamped on every conversations request; a response is applied
  // only when it belongs to the most recent one, so out-of-order arrivals (mount
  // race, fast filter toggles) can never overwrite newer state.
  const queueReqId = useRef(0);

  const refreshQueue = useCallback(
    (
      ds: string,
      f: ConversationFilters,
      p: number,
      q: string,
      lab: string,
    ) => {
      const reqId = ++queueReqId.current;
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
          if (reqId !== queueReqId.current) return;
          setConversations(res.items);
          setQueueTotal(res.total);
        })
        .catch((e) => {
          if (reqId !== queueReqId.current) return;
          fail(e);
        })
        .finally(() => {
          if (reqId !== queueReqId.current) return;
          setQueueLoading(false);
        });
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
    setLabelersReadyFor(null);
    void refreshTaxonomy(dataset);
    refreshStats(dataset);
    refreshBertopicLabels(dataset);
    refreshLabelers(dataset);
  }, [
    dataset,
    refreshTaxonomy,
    refreshStats,
    refreshBertopicLabels,
    refreshLabelers,
  ]);

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

  // Gate the queue fetch until the active dataset's labelers query has settled,
  // so the resolved labeler (see resolveLabeler) is known before the first
  // request. A legitimately-empty resolution still fetches unfiltered.
  useEffect(() => {
    if (!dataset) return;
    if (labelersReadyFor !== dataset) return;
    refreshQueue(dataset, filters, page, search, labeler);
  }, [dataset, labelersReadyFor, filters, page, search, labeler, refreshQueue]);

  const selectSegment = useCallback((segment: SegmentSummary) => {
    setSelectedSegment(segment);
    setTopic(segment.topic ?? "");
    setSubtopic(segment.subtopic ?? "");
  }, []);

  const loadConversation = useCallback(
    (conversation: string, selectId?: number) => {
      if (!dataset) return;
      setSelectedConversation(conversation);
      setViewLoading(true);
      api
        .getConversation(dataset, conversation)
        .then((v) => {
          setView(v);
          const sorted = [...v.segments].sort(
            (a, b) =>
              (a.message_indices[0] ?? 0) - (b.message_indices[0] ?? 0),
          );
          // After a refetch, re-select a requested segment (auto-advance target)
          // when present; otherwise fall back to the first in document order.
          const target =
            (selectId != null
              ? sorted.find((s) => s.id === selectId)
              : undefined) ?? sorted[0];
          if (target) {
            selectSegment(target);
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

  // After a successful save, refresh the queue/stats then advance selection:
  // to the next segment of the current conversation (document order); if the
  // saved segment was the last, to the first segment of the next conversation
  // in the current queue page; at the very end of the queue, stay on the saved
  // segment. Routing selection through loadConversation avoids racing the
  // refetch (the target is picked once the reload resolves).
  const advanceAfterSave = useCallback(
    (savedSegment: SegmentSummary) => {
      if (!dataset) return;
      refreshQueue(dataset, filters, page, search, labeler);
      refreshStats(dataset);
      if (!selectedConversation) return;

      const segments = view
        ? [...view.segments].sort(
            (a, b) =>
              (a.message_indices[0] ?? 0) - (b.message_indices[0] ?? 0),
          )
        : [];
      const curIdx = segments.findIndex((s) => s.id === savedSegment.id);
      const nextSegment = curIdx >= 0 ? segments[curIdx + 1] : undefined;
      if (nextSegment) {
        loadConversation(selectedConversation, nextSegment.id);
        return;
      }

      const convIdx = conversations.findIndex(
        (c) => c.conversation === selectedConversation,
      );
      const nextConv = convIdx >= 0 ? conversations[convIdx + 1] : undefined;
      if (nextConv) {
        loadConversation(nextConv.conversation);
      } else {
        loadConversation(selectedConversation, savedSegment.id);
      }
    },
    [
      dataset,
      filters,
      page,
      search,
      labeler,
      refreshQueue,
      refreshStats,
      selectedConversation,
      view,
      conversations,
      loadConversation,
    ],
  );

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
        advanceAfterSave(selectedSegment);
      })
      .catch(fail)
      .finally(() => setSaving(false));
  }, [
    dataset,
    selectedSegment,
    topic,
    subtopic,
    reviewedBy,
    advanceAfterSave,
    history,
    fail,
  ]);

  // "+ New topic…" from the annotation dropdown: formalize the typed name
  // (already slug-normalized, kind=user) then refetch so it joins the options.
  // The dropdown commits it as the segment topic once this resolves.
  const handleAddTopic = useCallback(
    async (name: string) => {
      if (!dataset || name.trim() === "") return;
      try {
        await api.createTaxonomy(dataset, {
          topic: name.trim(),
          kind: "user",
          domain: conversationDomain ?? undefined,
        });
        await refreshTaxonomy(dataset);
        toast.success(`Added "${name.trim()}" to taxonomy`);
      } catch (e) {
        fail(e);
      }
    },
    [dataset, refreshTaxonomy, conversationDomain, fail],
  );

  // "+ New subtopic…" from the annotation dropdown: create the (topic, subtopic)
  // option (slug-normalized, kind=user) then refetch so it scopes under the
  // topic for every annotator. The dropdown selects it once this resolves.
  const handleAddSubtopic = useCallback(
    async (parentTopic: string, name: string) => {
      if (!dataset || parentTopic.trim() === "" || name.trim() === "") return;
      try {
        await api.createTaxonomy(dataset, {
          topic: parentTopic.trim(),
          subtopic: name.trim(),
          kind: "user",
          domain: conversationDomain ?? undefined,
        });
        await refreshTaxonomy(dataset);
        toast.success(`Added "${name.trim()}" to ${parentTopic.trim()}`);
      } catch (e) {
        fail(e);
      }
    },
    [dataset, refreshTaxonomy, conversationDomain, fail],
  );

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
  const adjacentRef = useRef(selectAdjacentConversation);
  const undoRef = useRef(history.undo);
  const redoRef = useRef(history.redo);
  saveRef.current = handleSave;
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
            eb1 Annotation
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
          {labelers.length > 0 && (
            <div className="flex items-center gap-2">
              <UserRound className="size-4 text-muted-foreground" />
              <Select
                value={labeler || NO_LABELER}
                onValueChange={(v) =>
                  applyLabeler(v === NO_LABELER ? "" : v)
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
                  {labelers.map((l) => (
                    <SelectItem key={l} value={l}>
                      {l}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          <div className="ml-auto flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setTaxonomyManagerOpen(true)}
              disabled={!dataset}
            >
              <Tags className="size-4" />
              Manage taxonomy
            </Button>
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
                bertopicLabels={bertopicLabels}
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
                    taxonomy={annotationTaxonomy}
                    usedTopics={usedTopics}
                    topic={topic}
                    subtopic={subtopic}
                    reviewedBy={reviewedBy}
                    reviewedByLocked={ssoEnabled}
                    saving={saving}
                    onAddTopic={handleAddTopic}
                    onAddSubtopic={handleAddSubtopic}
                    onTopicChange={(t) => {
                      setTopic(t);
                      setSubtopic("");
                    }}
                    onSubtopicChange={setSubtopic}
                    onReviewedByChange={setManualReviewedBy}
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
      <TaxonomyManager
        open={taxonomyManagerOpen}
        onOpenChange={(next) => {
          setTaxonomyManagerOpen(next);
          if (!next && dataset) void refreshTaxonomy(dataset);
        }}
        dataset={dataset}
        entries={taxonomyEntries}
        onChanged={() => refreshTaxonomy(dataset)}
      />
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
