import { useCallback, useMemo, useState } from "react";
import { Check, Pencil, Plus, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { api, type TaxonomyEntry } from "../api";
import { buildTaxonomyMap, sortedTopics } from "../lib/taxonomy";
import { formatLabel } from "../lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface TaxonomyManagerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  dataset: string;
  entries: TaxonomyEntry[];
  /** Refetch taxonomy + used-topics so the labeling combobox updates at once. */
  onChanged: () => void | Promise<void>;
}

/**
 * Topic-management dialog wired to the taxonomy CRUD endpoints. Lists the
 * dataset's topics, supports inline rename (cascades labels server-side), delete,
 * a top "Add topic" input, and a merge action. Every mutation refetches the
 * taxonomy (via `onChanged`) so the annotation combobox reflects it immediately.
 */
function TaxonomyManager({
  open,
  onOpenChange,
  dataset,
  entries,
  onChanged,
}: TaxonomyManagerProps) {
  const topics = useMemo(
    () => sortedTopics(buildTaxonomyMap(entries)),
    [entries],
  );

  const [newTopic, setNewTopic] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [mergeFrom, setMergeFrom] = useState("");
  const [mergeInto, setMergeInto] = useState("");
  const [busy, setBusy] = useState(false);

  const run = useCallback(
    async (work: () => Promise<unknown>, success: string) => {
      if (!dataset) return;
      setBusy(true);
      try {
        await work();
        await onChanged();
        toast.success(success);
      } catch (e) {
        toast.error(String(e));
      } finally {
        setBusy(false);
      }
    },
    [dataset, onChanged],
  );

  const addTopic = useCallback(async () => {
    const name = newTopic.trim();
    if (!name) return;
    await run(
      () => api.createTaxonomy(dataset, { topic: name, kind: "user" }),
      `Added "${name}"`,
    );
    setNewTopic("");
  }, [newTopic, run, dataset]);

  const startEdit = useCallback((topic: string) => {
    setEditing(topic);
    setEditValue(topic);
  }, []);

  const saveEdit = useCallback(
    async (topic: string) => {
      const next = editValue.trim();
      if (!next || next === topic) {
        setEditing(null);
        return;
      }
      await run(
        () =>
          api.renameTaxonomy(dataset, {
            topic,
            new_topic: next,
            kind: "user",
          }),
        `Renamed to "${next}"`,
      );
      setEditing(null);
    },
    [editValue, run, dataset],
  );

  const removeTopic = useCallback(
    async (topic: string) => {
      await run(
        () => api.deleteTaxonomy(dataset, { topic, kind: "user" }),
        `Deleted "${topic}"`,
      );
    },
    [run, dataset],
  );

  const doMerge = useCallback(async () => {
    if (!mergeFrom || !mergeInto || mergeFrom === mergeInto) return;
    await run(
      () =>
        api.mergeTaxonomy(dataset, {
          from_topic: mergeFrom,
          into_topic: mergeInto,
          kind: "user",
        }),
      `Merged "${mergeFrom}" into "${mergeInto}"`,
    );
    setMergeFrom("");
    setMergeInto("");
  }, [mergeFrom, mergeInto, run, dataset]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Manage taxonomy</DialogTitle>
          <DialogDescription>
            Topics for {dataset}. Renames cascade to existing labels.
          </DialogDescription>
        </DialogHeader>

        <div className="flex items-center gap-2">
          <Input
            value={newTopic}
            onChange={(e) => setNewTopic(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void addTopic();
              }
            }}
            placeholder="New topic name…"
            aria-label="New topic name"
            className="h-8 text-sm"
          />
          <Button
            size="sm"
            onClick={() => void addTopic()}
            disabled={busy || newTopic.trim() === ""}
          >
            <Plus />
            Add topic
          </Button>
        </div>

        <ScrollArea className="h-56 rounded-lg border border-border">
          <ul className="divide-y divide-border">
            {topics.length === 0 && (
              <li className="px-3 py-6 text-center text-sm text-muted-foreground">
                No topics yet.
              </li>
            )}
            {topics.map((topic) => (
              <li
                key={topic}
                className="flex items-center gap-2 px-3 py-1.5 text-sm"
              >
                {editing === topic ? (
                  <>
                    <Input
                      value={editValue}
                      onChange={(e) => setEditValue(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          void saveEdit(topic);
                        } else if (e.key === "Escape") {
                          setEditing(null);
                        }
                      }}
                      aria-label={`Rename ${topic}`}
                      className="h-7 text-sm"
                      autoFocus
                    />
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      onClick={() => void saveEdit(topic)}
                      disabled={busy}
                      aria-label={`Save ${topic}`}
                    >
                      <Check />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      onClick={() => setEditing(null)}
                      aria-label={`Cancel rename ${topic}`}
                    >
                      <X />
                    </Button>
                  </>
                ) : (
                  <>
                    <span className="flex-1 truncate">{formatLabel(topic)}</span>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      onClick={() => startEdit(topic)}
                      aria-label={`Rename ${topic}`}
                    >
                      <Pencil />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      onClick={() => void removeTopic(topic)}
                      disabled={busy}
                      aria-label={`Delete ${topic}`}
                    >
                      <Trash2 />
                    </Button>
                  </>
                )}
              </li>
            ))}
          </ul>
        </ScrollArea>

        <Separator />

        <div className="flex flex-col gap-2">
          <span className="text-xs font-medium text-muted-foreground">
            Merge topics
          </span>
          <div className="flex items-center gap-2">
            <Select value={mergeFrom} onValueChange={setMergeFrom}>
              <SelectTrigger size="sm" className="flex-1" aria-label="Merge from">
                <SelectValue placeholder="From…" />
              </SelectTrigger>
              <SelectContent>
                {topics.map((t) => (
                  <SelectItem key={t} value={t}>
                    {formatLabel(t)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <span className="text-xs text-muted-foreground">into</span>
            <Select value={mergeInto} onValueChange={setMergeInto}>
              <SelectTrigger size="sm" className="flex-1" aria-label="Merge into">
                <SelectValue placeholder="Into…" />
              </SelectTrigger>
              <SelectContent>
                {topics.map((t) => (
                  <SelectItem key={t} value={t}>
                    {formatLabel(t)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              variant="outline"
              size="sm"
              onClick={() => void doMerge()}
              disabled={
                busy ||
                !mergeFrom ||
                !mergeInto ||
                mergeFrom === mergeInto
              }
            >
              Merge
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export default TaxonomyManager;
