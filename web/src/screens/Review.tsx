import { useState } from "react";
import type { Draft, Gap, Merged, Requirement, SelectedFact, Validation } from "../lib/types";

/** Screen 6.3 — the primary screen (R4).
 *
 * Three panels: what matched, what didn't, and the draft. The gaps panel is
 * the actionable half: a tailored resume tells you what you can say, and the
 * gap list tells you what you cannot, which is the part that changes what you
 * do next.
 *
 * Nothing here hides the Validator's work. A cut claim usually means a real
 * fact is missing from the knowledge base rather than that the Writer invented
 * something, so it is shown with its reason rather than quietly applied. */
export function Review({
  requirements,
  merged,
  draft,
  validation,
  gaps,
}: {
  requirements: { role_title?: string; requirements: Requirement[] };
  merged: Merged;
  draft: Draft;
  validation: Validation;
  gaps: Gap[];
}) {
  const [tab, setTab] = useState<"matches" | "gaps" | "draft">("draft");

  const absent = gaps.filter((gap) => gap.status === "absent");
  const weak = gaps.filter((gap) => gap.status === "weak");
  const covered = requirements.requirements.length - gaps.length;

  return (
    <div>
      <div className="flex gap-1 border-b border-stone-200 dark:border-stone-800">
        <Tab active={tab === "draft"} onClick={() => setTab("draft")}>
          Draft
          {!validation.clean && (
            <Pill tone="amber">{validation.cuts.length + validation.warnings.length}</Pill>
          )}
        </Tab>
        <Tab active={tab === "matches"} onClick={() => setTab("matches")}>
          Matches <Pill>{merged.counts.total}</Pill>
        </Tab>
        <Tab active={tab === "gaps"} onClick={() => setTab("gaps")}>
          Gaps
          {gaps.length > 0 && <Pill tone={absent.length ? "red" : "amber"}>{gaps.length}</Pill>}
        </Tab>
      </div>

      <div className="py-6">
        {tab === "draft" && <DraftPanel draft={draft} validation={validation} />}
        {tab === "matches" && (
          <MatchesPanel requirements={requirements.requirements} merged={merged} />
        )}
        {tab === "gaps" && (
          <GapsPanel absent={absent} weak={weak} covered={covered} merged={merged} />
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ draft */

function DraftPanel({ draft, validation }: { draft: Draft; validation: Validation }) {
  const cuts = new Map(validation.cuts.map((cut) => [cut.bullet, cut]));
  const warnings = new Map(validation.warnings.map((warning) => [warning.bullet, warning]));

  return (
    <div className="grid lg:grid-cols-[1fr_20rem] gap-8 items-start">
      <article className="space-y-6">
        {draft.summary && (
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-stone-500">
              Summary
            </h3>
            <p className="mt-2 leading-relaxed">{draft.summary}</p>
            <Sources ids={draft.summary_sources ?? []} />
          </section>
        )}

        {draft.skills && draft.skills.length > 0 && (
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-stone-500">
              Technical skills
            </h3>
            <ul className="mt-2 space-y-1">
              {draft.skills.map((group) => (
                <li key={group.group} className="text-sm">
                  <span className="font-medium">{group.group}:</span> {group.items.join(", ")}
                </li>
              ))}
            </ul>
          </section>
        )}

        {draft.sections.map((section, index) => (
          <section key={`${section.role_id ?? section.kind}-${index}`}>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-stone-500">
              {section.role_id ?? section.kind}
            </h3>
            <ul className="mt-2 space-y-3">
              {section.bullets.map((bullet) => {
                const cut = cuts.get(bullet.text);
                const warning = warnings.get(bullet.text);
                return (
                  <li
                    key={bullet.text}
                    className={`text-sm leading-relaxed pl-3 border-l-2 ${
                      cut
                        ? "border-red-400 opacity-60"
                        : warning
                          ? "border-amber-400"
                          : "border-stone-200 dark:border-stone-800"
                    }`}
                  >
                    <span className={cut ? "line-through" : ""}>
                      {bullet.lead && <strong>{bullet.lead}: </strong>}
                      {bullet.text}
                    </span>
                    <Sources ids={bullet.sources} />
                    {cut && (
                      <Note tone="red" label={cut.replacement ? "corrected" : "cut"}>
                        {cut.reason}
                      </Note>
                    )}
                    {warning && (
                      <Note tone="amber" label={warning.kind ?? "flagged"}>
                        {warning.reason}
                        {warning.kind === "nda" && (
                          <> — this will not be included in the exported PDF.</>
                        )}
                      </Note>
                    )}
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </article>

      <aside className="rounded border border-stone-200 dark:border-stone-800 p-4 text-sm sticky top-20">
        <h3 className="font-semibold">Validator</h3>
        {validation.clean ? (
          <p className="mt-2 text-emerald-700 dark:text-emerald-400">
            Every claim traces to a cited fact.
          </p>
        ) : (
          <>
            <p className="mt-2 text-stone-600 dark:text-stone-400">
              {validation.cuts.length} cut, {validation.warnings.length} flagged.
            </p>
            <p className="mt-3 text-xs text-stone-500 leading-relaxed">
              A cut usually means a real fact is missing from your knowledge base, not that
              the writer invented something. Adding it is the fix.
            </p>
          </>
        )}
      </aside>
    </div>
  );
}

/* ---------------------------------------------------------------- matches */

function MatchesPanel({
  requirements,
  merged,
}: {
  requirements: Requirement[];
  merged: Merged;
}) {
  const byRequirement = new Map<string, SelectedFact[]>();
  for (const fact of merged.facts) {
    for (const id of fact.requirement_ids) {
      byRequirement.set(id, [...(byRequirement.get(id) ?? []), fact]);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap gap-4 text-sm text-stone-600 dark:text-stone-400">
        <span>
          <strong className="text-stone-900 dark:text-stone-100">{merged.counts.both}</strong>{" "}
          found by both passes
        </span>
        <span>
          <strong className="text-stone-900 dark:text-stone-100">
            {merged.counts.selector_only}
          </strong>{" "}
          selector only
        </span>
        <span>
          <strong className="text-stone-900 dark:text-stone-100">
            {merged.counts.recall_only}
          </strong>{" "}
          recall only
        </span>
        <span>
          <strong className="text-stone-900 dark:text-stone-100">
            {merged.counts.rejected}
          </strong>{" "}
          considered and rejected
        </span>
      </div>

      <ul className="space-y-4">
        {requirements.map((requirement) => {
          const matches = byRequirement.get(requirement.id) ?? [];
          return (
            <li
              key={requirement.id}
              className="rounded border border-stone-200 dark:border-stone-800 p-4"
            >
              <div className="flex items-start gap-2">
                <span className="text-xs font-mono text-stone-400 mt-0.5">
                  {requirement.id}
                </span>
                <div className="flex-1">
                  <div className="font-medium text-sm">{requirement.text}</div>
                  <div className="text-xs text-stone-500 mt-0.5">
                    {requirement.kind}
                    {requirement.source === "inferred" && " · inferred from the posting"}
                  </div>
                  {requirement.quote && (
                    <blockquote className="mt-2 text-xs text-stone-500 border-l-2 border-stone-200 dark:border-stone-800 pl-2 italic">
                      {requirement.quote}
                    </blockquote>
                  )}
                </div>
              </div>

              {matches.length === 0 ? (
                <p className="mt-3 text-sm text-red-700 dark:text-red-400">Nothing matched.</p>
              ) : (
                <ul className="mt-3 space-y-2">
                  {matches.map((fact) => (
                    <li key={fact.fact_id} className="text-sm">
                      <div className="flex items-center gap-2 flex-wrap">
                        <code className="text-xs bg-stone-100 dark:bg-stone-900 px-1.5 py-0.5 rounded">
                          {fact.fact_id}
                        </code>
                        <Strength value={fact.strength} />
                        {fact.chosen_by !== "both" && (
                          <Pill tone="sky">{fact.chosen_by} only</Pill>
                        )}
                        {fact.depth && <span className="text-xs text-stone-500">{fact.depth}</span>}
                      </div>
                      <p className="mt-1 text-stone-600 dark:text-stone-400 text-xs leading-relaxed">
                        {fact.reason ?? fact.argument}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ul>

      {merged.considered_and_rejected.length > 0 && (
        <details className="rounded border border-stone-200 dark:border-stone-800 p-4">
          <summary className="cursor-pointer text-sm font-medium">
            Considered and rejected ({merged.considered_and_rejected.length})
          </summary>
          <p className="mt-2 text-xs text-stone-500">
            Proof these were read and judged, rather than never seen. If one of them should
            have been selected, that is a selection to argue with — not a silent omission.
          </p>
          <ul className="mt-3 space-y-2">
            {merged.considered_and_rejected.map((row) => (
              <li key={row.fact_id} className="text-sm">
                <code className="text-xs bg-stone-100 dark:bg-stone-900 px-1.5 py-0.5 rounded">
                  {row.fact_id}
                </code>
                <span className="ml-2 text-stone-600 dark:text-stone-400">{row.reason}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------- gaps */

function GapsPanel({
  absent,
  weak,
  covered,
  merged,
}: {
  absent: Gap[];
  weak: Gap[];
  covered: number;
  merged: Merged;
}) {
  return (
    <div className="space-y-6 max-w-3xl">
      <p className="text-sm text-stone-600 dark:text-stone-400">
        {covered} of {covered + absent.length + weak.length} requirements covered by a strong
        match.
      </p>

      {absent.length > 0 && (
        <section>
          <h3 className="text-sm font-semibold">Nothing in your knowledge base answers these</h3>
          <ul className="mt-3 space-y-2">
            {absent.map((gap) => (
              <li
                key={gap.requirement_id}
                className="rounded border border-red-200 dark:border-red-900 bg-red-50/50 dark:bg-red-950/20 p-3 text-sm"
              >
                <span className="font-medium">{gap.text}</span>
                <span className="ml-2 text-xs text-stone-500">{gap.kind}</span>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-stone-500 leading-relaxed">
            Each is either a real gap worth addressing in a cover letter, or a fact you have
            not written down yet. The second is far more common than it feels.
          </p>
        </section>
      )}

      {weak.length > 0 && (
        <section>
          <h3 className="text-sm font-semibold">Matched, but not strongly</h3>
          <ul className="mt-3 space-y-2">
            {weak.map((gap) => (
              <li
                key={gap.requirement_id}
                className="rounded border border-amber-200 dark:border-amber-900 bg-amber-50/50 dark:bg-amber-950/20 p-3 text-sm"
              >
                <span className="font-medium">{gap.text}</span>
                <div className="mt-1 text-xs text-stone-500">
                  matched by {gap.matched.join(", ") || "nothing"}
                </div>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-stone-500 leading-relaxed">
            Usually means the fact is real but its body is too thin to carry the claim.
            Expanding it in the knowledge base is the fix.
          </p>
        </section>
      )}

      {merged.tag_proposals.length > 0 && (
        <section>
          <h3 className="text-sm font-semibold">Suggested tags</h3>
          <p className="mt-1 text-xs text-stone-500">
            Found by the recall pass: facts that matched on content while their tags said
            otherwise.
          </p>
          <ul className="mt-3 space-y-2">
            {merged.tag_proposals.map((proposal) => (
              <li
                key={proposal.fact_id}
                className="rounded border border-stone-200 dark:border-stone-800 p-3 text-sm"
              >
                <code className="text-xs bg-stone-100 dark:bg-stone-900 px-1.5 py-0.5 rounded">
                  {proposal.fact_id}
                </code>
                <span className="ml-2">+ {proposal.add_tags.join(", ")}</span>
                {proposal.why && (
                  <p className="mt-1 text-xs text-stone-500 leading-relaxed">{proposal.why}</p>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {absent.length === 0 && weak.length === 0 && (
        <p className="text-sm text-emerald-700 dark:text-emerald-400">
          No gaps. Every requirement is matched by a strong fact.
        </p>
      )}
    </div>
  );
}

/* --------------------------------------------------------------- fragments */

function Tab({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2 text-sm border-b-2 -mb-px flex items-center gap-2 ${
        active
          ? "border-stone-900 dark:border-stone-100 font-medium"
          : "border-transparent text-stone-500 hover:text-stone-800 dark:hover:text-stone-200"
      }`}
    >
      {children}
    </button>
  );
}

function Pill({
  children,
  tone = "stone",
}: {
  children: React.ReactNode;
  tone?: "stone" | "amber" | "red" | "sky";
}) {
  const tones = {
    stone: "bg-stone-200 dark:bg-stone-800 text-stone-700 dark:text-stone-300",
    amber: "bg-amber-200 dark:bg-amber-900 text-amber-900 dark:text-amber-200",
    red: "bg-red-200 dark:bg-red-900 text-red-900 dark:text-red-200",
    sky: "bg-sky-100 dark:bg-sky-950 text-sky-800 dark:text-sky-300",
  };
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${tones[tone]}`}>{children}</span>
  );
}

function Strength({ value }: { value: string }) {
  const tones: Record<string, string> = {
    strong: "text-emerald-700 dark:text-emerald-400",
    moderate: "text-stone-500",
    weak: "text-amber-700 dark:text-amber-400",
  };
  return <span className={`text-xs ${tones[value] ?? "text-stone-500"}`}>{value}</span>;
}

function Sources({ ids }: { ids: string[] }) {
  if (ids.length === 0) return null;
  return (
    <div className="mt-1 flex flex-wrap gap-1">
      {ids.map((id) => (
        <code
          key={id}
          className="text-[11px] bg-stone-100 dark:bg-stone-900 text-stone-500 px-1 py-0.5 rounded"
        >
          {id}
        </code>
      ))}
    </div>
  );
}

function Note({
  tone,
  label,
  children,
}: {
  tone: "red" | "amber";
  label: string;
  children: React.ReactNode;
}) {
  const tones = {
    red: "text-red-700 dark:text-red-400",
    amber: "text-amber-700 dark:text-amber-400",
  };
  return (
    <p className={`mt-1 text-xs leading-relaxed ${tones[tone]}`}>
      <span className="font-medium uppercase tracking-wide">{label}</span> — {children}
    </p>
  );
}
