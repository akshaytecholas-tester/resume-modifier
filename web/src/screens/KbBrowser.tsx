import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, RequestFailed } from "../lib/api";
import type { IndexRow } from "../lib/types";

/** Screen 6.5 — browse and edit the knowledge base (R8, R13).
 *
 * The editor is raw text on purpose at this stage: every save goes through the
 * same validated write path as any other (AC-R13.3), and a structured form
 * that cannot express something would push edits outside that path, which is
 * worse than asking the user to read YAML. */
export function KbBrowser() {
  const [selected, setSelected] = useState<{ type: string; id: string } | null>(null);
  const [filter, setFilter] = useState("");
  const [facet, setFacet] = useState<string>("all");

  const index = useQuery({ queryKey: ["kb", "index"], queryFn: api.kbIndex });
  const validation = useQuery({ queryKey: ["kb", "validate"], queryFn: api.kbValidate });

  const entries = (index.data?.entries ?? []).filter((entry) => {
    if (facet !== "all" && entry.type !== facet) return false;
    if (!filter) return true;
    const needle = filter.toLowerCase();
    return (
      entry.id.includes(needle) ||
      entry.title.toLowerCase().includes(needle) ||
      entry.tags.some((tag) => tag.includes(needle))
    );
  });

  const types = Object.keys(index.data?.counts ?? {});

  return (
    <div className="grid lg:grid-cols-[22rem_1fr] gap-8 items-start">
      <aside className="space-y-3">
        <div className="flex gap-2">
          <input
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder="Search id, title or tag"
            className="flex-1 rounded border border-stone-300 dark:border-stone-700 bg-white dark:bg-stone-900 px-3 py-2 text-sm"
          />
          <select
            value={facet}
            onChange={(event) => setFacet(event.target.value)}
            className="rounded border border-stone-300 dark:border-stone-700 bg-white dark:bg-stone-900 px-2 text-sm"
          >
            <option value="all">all</option>
            {types.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </div>

        {validation.data && !validation.data.ok && (
          <div className="rounded border border-red-300 dark:border-red-900 bg-red-50 dark:bg-red-950/30 p-3 text-xs">
            <strong>{validation.data.errors.length} validation error(s)</strong>
            <ul className="mt-1 space-y-0.5">
              {validation.data.errors.slice(0, 5).map((issue, index) => (
                <li key={index}>
                  {issue.entry}: {issue.message}
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="text-xs text-stone-500 tabular-nums">
          {entries.length} of {index.data?.entries.length ?? 0} entries ·{" "}
          {(index.data?.estimated_corpus_tokens ?? 0).toLocaleString()} est. tokens
        </div>

        <ul className="space-y-1 max-h-[32rem] overflow-y-auto pr-1">
          {entries.map((entry) => (
            <EntryRow
              key={entry.id}
              entry={entry}
              active={selected?.id === entry.id}
              onClick={() => setSelected({ type: entry.type, id: entry.id })}
            />
          ))}
        </ul>
      </aside>

      {selected ? (
        <Editor key={selected.id} type={selected.type} id={selected.id} />
      ) : (
        <p className="text-sm text-stone-500">
          Pick an entry. Edits here go through the same validated write path as a text editor
          or an accepted proposal — and land as a commit in your local <code>kb/</code> repo.
        </p>
      )}
    </div>
  );
}

function EntryRow({
  entry,
  active,
  onClick,
}: {
  entry: IndexRow;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <li>
      <button
        onClick={onClick}
        className={`w-full text-left rounded px-2 py-1.5 text-sm ${
          active
            ? "bg-stone-200 dark:bg-stone-800"
            : "hover:bg-stone-100 dark:hover:bg-stone-900"
        }`}
      >
        <div className="flex items-center gap-2">
          <span className="truncate flex-1">{entry.title}</span>
          {entry.visibility !== "public" && (
            <span className="text-[10px] uppercase text-amber-700 dark:text-amber-400">
              {entry.visibility}
            </span>
          )}
          <span className="text-[10px] text-stone-400">{entry.depth}</span>
        </div>
        <div className="text-[11px] text-stone-400 font-mono truncate">{entry.id}</div>
      </button>
    </li>
  );
}

function Editor({ type, id }: { type: string; id: string }) {
  const queryClient = useQueryClient();
  const entry = useQuery({ queryKey: ["kb", "entry", type, id], queryFn: () => api.entry(type, id) });
  const history = useQuery({
    queryKey: ["kb", "history", type, id],
    queryFn: () => api.history(type, id),
  });

  const [draft, setDraft] = useState<string | null>(null);
  const [staleOnDisk, setStaleOnDisk] = useState(false);

  useEffect(() => {
    if (entry.data && draft === null) setDraft(entry.data.raw);
  }, [entry.data, draft]);

  // A watcher firing must never discard typing. If the file changed on disk
  // while there are unsaved edits, say so and let the user choose — silently
  // overwriting their draft would be worse than the conflict it avoids.
  useEffect(() => {
    if (entry.data && draft !== null && draft !== entry.data.raw) setStaleOnDisk(false);
  }, [entry.data, draft]);

  const dirty = draft !== null && entry.data != null && draft !== entry.data.raw;

  const save = useMutation({
    mutationFn: () => api.saveEntry(type, id, draft ?? "", entry.data!.hash),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["kb"] });
      setDraft(null);
    },
  });

  if (!entry.data || draft === null) return <p className="text-sm text-stone-500">Loading…</p>;

  const failure = save.error instanceof RequestFailed ? save.error : null;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3 flex-wrap">
        <h2 className="font-semibold">{id}</h2>
        {dirty && <span className="text-xs text-amber-700 dark:text-amber-400">unsaved</span>}
        <div className="ml-auto flex gap-2">
          <button
            onClick={() => setDraft(entry.data!.raw)}
            disabled={!dirty}
            className="rounded border border-stone-300 dark:border-stone-700 px-3 py-1.5 text-sm disabled:opacity-40"
          >
            Discard
          </button>
          <button
            onClick={() => save.mutate()}
            disabled={!dirty || save.isPending}
            className="rounded bg-stone-900 dark:bg-stone-100 text-stone-50 dark:text-stone-900 px-4 py-1.5 text-sm font-medium disabled:opacity-40"
          >
            {save.isPending ? "Saving…" : "Save"}
          </button>
        </div>
      </div>

      {staleOnDisk && (
        <div className="rounded border border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/30 p-3 text-sm">
          This file changed on disk. Your unsaved edits are intact — reload to take the disk
          version, or save to keep yours (the save will tell you if they conflict).
        </div>
      )}

      <textarea
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        spellCheck={false}
        rows={28}
        className="w-full rounded border border-stone-300 dark:border-stone-700 bg-white dark:bg-stone-900 p-3 font-mono text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-stone-400"
      />

      {failure && (
        <div className="rounded border border-red-300 dark:border-red-900 bg-red-50 dark:bg-red-950/30 p-3 text-sm">
          <div className="font-medium text-red-800 dark:text-red-300">{failure.message}</div>
          {failure.remedy && (
            <div className="mt-1 text-red-700 dark:text-red-400">{failure.remedy}</div>
          )}
          {Array.isArray(failure.detail) && (
            <ul className="mt-2 space-y-0.5 text-xs text-red-700 dark:text-red-400">
              {failure.detail.map((problem, index) => (
                <li key={index}>{JSON.stringify(problem)}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {save.data && save.data.warnings.length > 0 && (
        <div className="rounded border border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/30 p-3 text-xs">
          {save.data.warnings.map((warning, index) => (
            <div key={index}>{warning.message}</div>
          ))}
        </div>
      )}

      {history.data && history.data.commits.length > 0 && (
        <details className="rounded border border-stone-200 dark:border-stone-800 p-3">
          <summary className="cursor-pointer text-sm font-medium">
            History ({history.data.commits.length})
          </summary>
          <ul className="mt-2 space-y-1 text-xs">
            {history.data.commits.map((commit) => (
              <li key={commit.sha} className="flex items-center gap-2">
                <code className="text-stone-400">{commit.sha.slice(0, 8)}</code>
                <span className="flex-1 truncate">{commit.message}</span>
                <button
                  onClick={async () => {
                    await api.revert(type, id, commit.sha);
                    queryClient.invalidateQueries({ queryKey: ["kb"] });
                    setDraft(null);
                  }}
                  className="text-stone-500 hover:text-stone-900 dark:hover:text-stone-100"
                >
                  revert
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
