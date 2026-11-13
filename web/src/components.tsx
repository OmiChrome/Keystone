import React, { createContext, useContext, useEffect, useRef, useState } from "react";
import { AgentResult, Confidence, Evidence, Job, JobEvent, api } from "./api";

/* ------------------------------------------------------------------ small atoms */

export function Badge({ tone = "neutral", children }: { tone?: string; children: React.ReactNode }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

const VERDICT_TONE: Record<string, string> = {
  comply: "good", included: "good", deviate: "bad", excluded: "bad", missing: "warn", not_mentioned: "warn",
  unclear: "muted", qualified: "warn", critical: "bad", high: "warn", medium: "info", low: "muted",
};
export const Verdict = ({ v }: { v: string }) => <Badge tone={VERDICT_TONE[v] ?? "neutral"}>{v.replace("_", " ")}</Badge>;

export function ConfBar({ c }: { c: Confidence | null | undefined }) {
  if (!c) return <span className="muted">—</span>;
  const factors = Object.entries(c.factors || {})
    .map(([k, v]) => `${k.replace(/_/g, " ")}: ${typeof v === "number" ? v.toFixed(2) : v}`)
    .join("\n");
  return (
    <span className="conf" title={`${c.rationale || "confidence"}\n${factors}`}>
      <span className={`conf-track conf-${c.level}`}>
        <span className="conf-fill" style={{ width: `${Math.round(c.score * 100)}%` }} />
      </span>
      <span className="conf-num">{c.score.toFixed(2)}</span>
    </span>
  );
}

export function Stat({ label, value, sub, tone }: { label: string; value: React.ReactNode; sub?: React.ReactNode; tone?: string }) {
  return (
    <div className={`stat ${tone ? "stat-" + tone : ""}`}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  );
}

export function Card({ title, actions, children, className = "" }: { title?: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-head">
          <h3>{title}</h3>
          <div className="card-actions">{actions}</div>
        </header>
      )}
      {children}
    </section>
  );
}

/* ------------------------------------------------------------------ evidence drawer */

type EvCtx = { open: (e: Evidence) => void };
const EvidenceContext = createContext<EvCtx>({ open: () => {} });
export const useEvidence = () => useContext(EvidenceContext);

const norm = (s: string) => s.toLowerCase().replace(/\s+/g, " ");

function highlight(text: string, quote: string): React.ReactNode {
  if (!quote) return text;
  // map normalized positions back onto the original text so line breaks survive
  const idxMap: number[] = [];
  let flat = "";
  let prevSpace = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    const sp = /\s/.test(ch);
    if (sp && prevSpace) continue;
    flat += sp ? " " : ch.toLowerCase();
    idxMap.push(i);
    prevSpace = sp;
  }
  const q = norm(quote).trim();
  let at = flat.indexOf(q);
  let len = q.length;
  if (at < 0) {
    // fall back: longest prefix of the quote that appears
    for (let n = Math.min(q.length, 120); n >= 12; n -= 4) {
      at = flat.indexOf(q.slice(0, n));
      if (at >= 0) { len = n; break; }
    }
  }
  if (at < 0) return text;
  const s = idxMap[at];
  const e = idxMap[Math.min(at + len - 1, idxMap.length - 1)] + 1;
  return (
    <>
      {text.slice(0, s)}
      <mark id="ev-mark">{text.slice(s, e)}</mark>
      {text.slice(e)}
    </>
  );
}

export function EvidenceProvider({ children }: { children: React.ReactNode }) {
  const [ev, setEv] = useState<Evidence | null>(null);
  const [page, setPage] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    setPage(null);
    setErr(null);
    if (!ev || ev.url || ev.doc_id === "reference") return;
    api.doc(ev.doc_id, ev.page ?? undefined).then(setPage).catch((e) => setErr(String(e)));
  }, [ev]);
  useEffect(() => {
    if (page) setTimeout(() => document.getElementById("ev-mark")?.scrollIntoView({ block: "center" }), 50);
  }, [page]);
  const text: string | undefined = page?.text ?? (page?.pages ? page.pages.join("\n\n") : undefined);
  return (
    <EvidenceContext.Provider value={{ open: setEv }}>
      {children}
      {ev && (
        <div className="drawer-backdrop" onClick={() => setEv(null)}>
          <aside className="drawer" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Source evidence">
            <header className="drawer-head">
              <div>
                <div className="eyebrow">Source</div>
                <h3>{ev.doc_name}</h3>
                <div className="muted small">
                  {ev.page ? `page ${ev.page}` : ev.locator ?? ""} · match {ev.match_score.toFixed(0)}/100 ·{" "}
                  {ev.verified ? <Badge tone="good">quote verified in source</Badge> : <Badge tone="bad">quote NOT found in source</Badge>}
                </div>
              </div>
              <button className="btn btn-ghost" onClick={() => setEv(null)} aria-label="Close">✕</button>
            </header>
            <blockquote className="quote">“{ev.quote}”</blockquote>
            {ev.url ? (
              <p>
                Published source: <a href={ev.url} target="_blank" rel="noreferrer">{ev.url}</a>
              </p>
            ) : (
              <>
                {err && <p className="error">{err}</p>}
                {!text && !err && <p className="muted">Loading page…</p>}
                {text && <pre className="page-text">{highlight(text, ev.quote)}</pre>}
                <a className="btn btn-ghost small" href={`/api/documents/${ev.doc_id}/file`} target="_blank" rel="noreferrer">Open original file ↗</a>
              </>
            )}
          </aside>
        </div>
      )}
    </EvidenceContext.Provider>
  );
}

export function Cite({ ev, label }: { ev: Evidence | null | undefined; label?: string }) {
  const { open } = useEvidence();
  if (!ev || !ev.quote) return <span className="muted small">no citation</span>;
  return (
    <button className={`cite ${ev.verified ? "cite-ok" : "cite-bad"}`} onClick={() => open(ev)} title={ev.quote}>
      <span className="cite-icon">{ev.verified ? "✓" : "!"}</span>
      {label ?? `${ev.doc_name.replace(/\.(pdf|csv)$/i, "")}${ev.page ? ` p${ev.page}` : ev.locator ? ` ${ev.locator}` : ""}`}
    </button>
  );
}

/* ------------------------------------------------------------------ job runner */

export function useJob() {
  const [job, setJob] = useState<Job | null>(null);
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | null>(null);

  const stop = () => {
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = null;
  };
  useEffect(() => stop, []);

  const run = async (path: string, body: unknown) => {
    stop();
    setError(null);
    setEvents([]);
    setJob({ job_id: "", kind: path, status: "running", elapsed_s: 0, events: [], n_events: 0, result: null, error: null });
    try {
      const { job_id } = await api.start(path, body);
      let seen = 0;
      const poll = async () => {
        try {
          const j = await api.job(job_id, seen);
          seen = j.n_events;
          if (j.events.length) setEvents((e) => [...e, ...j.events]);
          setJob(j);
          if (j.status === "running") timer.current = window.setTimeout(poll, 1200);
          else if (j.status === "error") setError(j.error);
        } catch (e) {
          setError(String(e));
        }
      };
      poll();
    } catch (e) {
      setError(String(e));
      setJob(null);
    }
  };
  return { job, events, error, run, result: job?.result ?? null, running: job?.status === "running" };
}

const PURPOSE_LABEL: Record<string, string> = {
  "compliance:extract": "Extracting requirements from spec",
  "compliance:review": "Reviewing submittal against requirements",
  "compliance:verify": "Independent second-model check",
  "bids:extract": "Reading bid & mapping scope",
  "bids:scope": "Deriving scope checklist",
  "bids:memo": "Drafting award memo (number-grounded)",
  "leadtime:classify": "Classifying equipment",
  "schedule:briefing": "Writing risk briefing (number-grounded)",
};

export function JobLog({ job, events, error }: { job: Job | null; events: JobEvent[]; error: string | null }) {
  if (!job && !error) return null;
  return (
    <div className={`joblog ${job?.status === "running" ? "joblog-live" : ""}`}>
      <div className="joblog-head">
        {job?.status === "running" && <span className="spinner" aria-hidden />}
        <strong>{job?.status === "running" ? "Working…" : job?.status === "done" ? "Done" : "Stopped"}</strong>
        <span className="muted">{job ? `${job.elapsed_s.toFixed(0)}s` : ""}</span>
        <span className="muted">· {events.filter((e) => e.event === "llm_call").length} model calls</span>
      </div>
      {error && <div className="error">{error}</div>}
      <ol className="joblog-list">
        {events.map((e, i) => (
          <li key={i} className={e.event === "llm_retry" ? "warn" : ""}>
            <span className="mono small">{e.model}</span>
            <span>{e.event === "llm_retry" ? `retry (HTTP ${e.status}) – ` : ""}{PURPOSE_LABEL[e.purpose ?? ""] ?? e.purpose}</span>
            <span className="muted small">{e.cached ? "cache hit" : e.latency_s != null ? `${e.latency_s}s` : ""}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

/* ------------------------------------------------------------------ envelope header + raw json */

export function ResultHeader({ r }: { r: AgentResult }) {
  const [raw, setRaw] = useState(false);
  return (
    <>
      <div className={`envelope envelope-${r.status}`}>
        <div className="envelope-main">
          <div className="eyebrow">
            {r.agent} · run {r.run_id} · {r.schema_version}
          </div>
          <p className="summary">{r.summary}</p>
        </div>
        <div className="envelope-side">
          <div className="small muted">confidence</div>
          <ConfBar c={r.confidence} />
          <div className="small muted" style={{ marginTop: 8 }}>
            {r.usage.llm_calls} calls ({r.usage.cached_calls} cached) · ${r.usage.cost_usd.toFixed(4)} · {r.usage.wall_time_s}s
          </div>
          <div className="small muted">{r.usage.models.join(", ") || "no LLM used"}</div>
          <button className="btn btn-ghost small" onClick={() => setRaw(!raw)}>{raw ? "Hide" : "Show"} JSON</button>
        </div>
      </div>
      {r.human_review.required && (
        <div className="handoff">
          <strong>Handed to a human</strong> — the agent is not sure enough to act alone:
          <ul>{r.human_review.reasons.slice(0, 8).map((x, i) => <li key={i}>{x}</li>)}</ul>
          {r.human_review.reasons.length > 8 && <div className="muted small">+{r.human_review.reasons.length - 8} more</div>}
        </div>
      )}
      {raw && <pre className="json">{JSON.stringify(r, null, 1)}</pre>}
    </>
  );
}
