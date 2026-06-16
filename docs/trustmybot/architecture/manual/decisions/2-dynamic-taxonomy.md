# 2. Dynamic taxonomy: DB-canonical, exported JSON, pipeline dynamic-load

- Status: Accepted
- Date: 2026-06-16
- Scope: `annotation/` (taxonomy CRUD + export), `config/taxonomy/`, `pipeline/` MetadataProvider (consumer, task 16b)

## Context

The labeling taxonomy (per-dataset `(topic, subtopic)` options) was hardcoded in
two places that drifted: the annotation Postgres `taxonomy` table (read by the
relabel UI) and the pipeline analyzer's categories (a SQLite `MetadataProvider`).
The Founder needs to **edit the taxonomy from the website** — add an option,
rename one, merge two — and have both the website and the pipeline pick the
change up with no code change. A rename must not orphan the labels already
applied to `segment` rows.

## Decision

**The annotation Postgres `taxonomy` table is the single canonical source.** The
website edits it directly (CRUD below). The pipeline does **not** read the DB;
instead the table is **exported per-dataset to JSON** (`config/taxonomy/{dataset}.json`),
and the pipeline's `MetadataProvider` **loads that JSON dynamically at runtime,
falling back to its bundled SQLite taxonomy when no JSON exists** (task 16b). A
human edit therefore flows: website → DB → `export_taxonomy` → JSON → pipeline.

### CRUD with label cascade (`annotation/backend/db.py` + `routes.py`)

The `taxonomy` table gains a `UNIQUE (dataset, kind, topic, subtopic)` index
(`NULLS NOT DISTINCT`, PG15+) so create/merge are idempotent.

| op | endpoint | behaviour |
|---|---|---|
| create | `POST /datasets/{ds}/taxonomy` | insert `{kind=user, topic, subtopic?, description?}`; duplicate is a no-op (`ON CONFLICT DO NOTHING`) |
| rename | `PATCH /datasets/{ds}/taxonomy` | update the taxonomy entry **and cascade** to matching `segment` rows, one transaction |
| merge | `POST /datasets/{ds}/taxonomy/merge` | re-home `from_topic` segments + options under `into_topic`, drop the leftover `from_topic` rows |
| delete | `DELETE /datasets/{ds}/taxonomy?topic=&subtopic=` | remove the option only; applied labels are left intact |
| export | (CLI) `python -m annotation.export_taxonomy --dataset {ds}` | write `config/taxonomy/{ds}.json` |

### Cascade semantics

A segment is tied to a dataset through `segment.conversation_id → conversation.dataset`.

- **Rename, topic-level** (no `subtopic`): set `taxonomy.topic` and every
  `segment.topic = old` in the dataset to the new name.
- **Rename, subtopic-level** (`subtopic` given): set the entry's `(topic, subtopic)`
  and every segment whose `(topic, subtopic)` matches the old pair.
- **Merge**: every `segment.topic = from_topic` in the dataset becomes
  `into_topic`; the `from_topic` taxonomy options move under `into_topic` (skipping
  any that would collide with an existing `into_topic` option) and the leftover
  `from_topic` rows are deleted. The result is a single taxonomy entry per option.
- **Delete is not erasing history**: removing an option leaves segments already
  labelled with it unchanged — the option simply disappears from the picker.

Rename and merge run in one transaction so the entry and its labels never
disagree.

### Export JSON schema (`config/taxonomy/{dataset}.json`)

```json
{
  "dataset": "wildchat",
  "kind_default": "user",
  "entries": [
    {"kind": "user", "topic": "coding_help", "subtopic": "binary_search", "description": "..."},
    {"kind": "user", "topic": "writing_help", "subtopic": null, "description": null}
  ]
}
```

`entries` are sorted by `(kind, topic, subtopic)` (NULLs first) so the file is
byte-stable for a given DB state — re-exporting an unchanged taxonomy produces an
identical file, and the diff of an edit is minimal.

## Consequences

- The website is the only writer of the taxonomy; the pipeline is a read-only
  consumer of the exported JSON, so the two can never silently diverge — at worst
  the JSON is stale until the next export.
- Renames/merges are **history-preserving**: applied labels move with the rename,
  so analytics over `segment.topic` stay correct without a backfill.
- The export is a manual/triggered step (a CLI), not a live read; the operator
  runs it (or CI does) after editing the taxonomy. Deleting an option does not
  touch the JSON's already-applied labels because labels live on `segment`, not in
  the export.
- Open-vocab labeling is unchanged: the labeling combobox still accepts arbitrary
  names (de-facto proposals); this ADR only makes the *formal option list*
  editable and exportable. A proposal approval workflow is out of scope.
