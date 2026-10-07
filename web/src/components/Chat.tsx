import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, RequestFailed } from "../lib/api";

/** Screen 6.4. Revision by conversation (R5).
 *
 * Every turn re-enters the pipeline at the Writer and **always** re-runs the
 * Validator (AC-R5.2). Chat cannot bypass validation, or "just add that I led
 * the team" writes an unsupported claim straight into the document. */
export function Chat({ runId, disabled }: { runId: string; disabled: boolean }) {
  const [message, setMessage] = useState("");
  const queryClient = useQueryClient();

  const history = useQuery({
    queryKey: ["chat", runId],
    queryFn: () => api.chatHistory(runId),
  });

  const send = useMutation({
    mutationFn: () => api.chat(runId, message.trim()),
    onSuccess: () => {
      setMessage("");
      queryClient.invalidateQueries({ queryKey: ["chat", runId] });
    },
  });

  const turns = history.data?.turns ?? [];

  return (
    <section className="mt-8 rounded border border-stone-200 dark:border-stone-800 p-4">
      <h2 className="text-sm font-semibold">Revise</h2>
      <p className="mt-1 text-xs text-stone-500 leading-relaxed">
        Every revision re-runs the validator. If a request needs a fact you have not recorded,
        it will be cut and you will be told why — that is the cue to add the fact, not to
        re-ask.
      </p>

      {turns.length > 0 && (
        <ul className="mt-4 space-y-2">
          {turns.map((turn, index) => (
            <li
              key={index}
              className={`text-sm rounded px-3 py-2 ${
                turn.role === "user"
                  ? "bg-stone-100 dark:bg-stone-900"
                  : "text-stone-500 text-xs"
              }`}
            >
              {turn.text}
              {turn.clean === false && (
                <span className="ml-2 text-amber-700 dark:text-amber-400">
                  — the validator made changes
                </span>
              )}
            </li>
          ))}
        </ul>
      )}

      <div className="mt-4 flex gap-2">
        <input
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && message.trim() && !disabled) send.mutate();
          }}
          disabled={disabled || send.isPending}
          placeholder="Lead with the trading engine; drop the award bullet"
          className="flex-1 rounded border border-stone-300 dark:border-stone-700 bg-white dark:bg-stone-900 px-3 py-2 text-sm disabled:opacity-50"
        />
        <button
          onClick={() => send.mutate()}
          disabled={!message.trim() || disabled || send.isPending}
          className="rounded bg-stone-900 dark:bg-stone-100 text-stone-50 dark:text-stone-900 px-4 py-2 text-sm font-medium disabled:opacity-40"
        >
          {send.isPending ? "…" : "Send"}
        </button>
      </div>

      {send.error instanceof RequestFailed && (
        <p className="mt-2 text-sm text-red-700 dark:text-red-400">
          {send.error.message} {send.error.remedy}
        </p>
      )}
    </section>
  );
}
