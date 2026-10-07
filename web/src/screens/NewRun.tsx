import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, RequestFailed } from "../lib/api";

/** Screen 6.1. Paste the posting and go. */
export function NewRun({ onStarted }: { onStarted: (runId: string) => void }) {
  const [text, setText] = useState("");
  const [company, setCompany] = useState("");

  const start = useMutation({
    mutationFn: () => api.startRun(text.trim(), company.trim() || undefined),
    onSuccess: (result) => onStarted(result.run_id),
  });

  return (
    <div className="max-w-3xl">
      <h1 className="text-2xl font-semibold tracking-tight">Tailor to a posting</h1>
      <p className="mt-2 text-stone-600 dark:text-stone-400">
        Paste the job description. Five agents read your whole knowledge base against it and
        report what matched, what didn't, and what they cut.
      </p>

      <label className="block mt-6 text-sm font-medium" htmlFor="posting">
        Job description
      </label>
      <textarea
        id="posting"
        value={text}
        onChange={(event) => setText(event.target.value)}
        rows={16}
        placeholder="Paste the full posting — responsibilities and requirements both. The analyst reads what a posting implies as well as what it lists."
        className="mt-2 w-full rounded border border-stone-300 dark:border-stone-700 bg-white dark:bg-stone-900 p-3 font-mono text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-stone-400"
      />

      <div className="mt-4 flex items-end gap-4">
        <div className="flex-1 max-w-xs">
          <label className="block text-sm font-medium" htmlFor="company">
            Company <span className="text-stone-400 font-normal">(optional)</span>
          </label>
          <input
            id="company"
            value={company}
            onChange={(event) => setCompany(event.target.value)}
            className="mt-2 w-full rounded border border-stone-300 dark:border-stone-700 bg-white dark:bg-stone-900 px-3 py-2 text-sm"
            placeholder="Used in the run's folder name"
          />
        </div>
        <button
          onClick={() => start.mutate()}
          disabled={!text.trim() || start.isPending}
          className="rounded bg-stone-900 dark:bg-stone-100 text-stone-50 dark:text-stone-900 px-5 py-2 text-sm font-medium disabled:opacity-40 hover:opacity-90"
        >
          {start.isPending ? "Starting…" : "Run the pipeline"}
        </button>
      </div>

      {start.error instanceof RequestFailed && (
        <div className="mt-4 rounded border border-red-300 dark:border-red-900 bg-red-50 dark:bg-red-950/40 p-3 text-sm">
          <div className="font-medium text-red-800 dark:text-red-300">
            {start.error.message}
          </div>
          {start.error.remedy && (
            <div className="mt-1 text-red-700 dark:text-red-400">{start.error.remedy}</div>
          )}
        </div>
      )}
    </div>
  );
}
