import React, { useEffect, useState } from "react";
import { AgentResult, DocInfo, api } from "./api";
import { Badge, Card, EvidenceProvider, ResultHeader } from "./components";
import { BidsPage, BidsResult, CompliancePage, ComplianceResult, LeadTimePage, LeadTimeResult, PageIntro, PipelinePage, SchedulePage, ScheduleResult, Workspace } from "./pages";

const NAV = [
  ["overview", "Overview"],
  ["pipeline", "Package pipeline"],
  ["compliance", "Spec compliance"],
  ["bids", "Bid leveling"],
  ["leadtime", "Lead time"],
  ["schedule", "Schedule risk"],
  ["audit", "Audit log"],
  ["connect", "Connect via MCP"],
] as const;
type Route = (typeof NAV)[number][0];

function Logo() {
  return (
    <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden>
      <path d="M4 28 L10 6 H22 L28 28 H20 L16 14 L12 28 Z" fill="var(--accent)" />
      <path d="M13 6 H19 L17.5 11 H14.5 Z" fill="var(--ink)" />
    </svg>
  );
}

export default function App() {
  const [route, setRoute] = useState<Route>(() => (location.hash.slice(1) as Route) || "overview");
  const [ws, setWs] = useState<Workspace>({ sample: null, docs: [] });
  const [health, setHealth] = useState<any>(null);
  const [loading, setLoading] = useState<string | null>(null);
  const [navOpen, setNavOpen] = useState(false);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth({ ok: false }));
    const h = () => setRoute((location.hash.slice(1) as Route) || "overview");
    window.addEventListener("hashchange", h);
    return () => window.removeEventListener("hashchange", h);
  }, []);
  const go = (r: Route) => {
    location.hash = r;
    setNavOpen(false);
  };

  const load = async (p: string) => {
    setLoading(p);
    try {
      const s = await api.loadSample(p);
      setWs({ sample: s, docs: Object.values(s.docs) });
    } finally {
      setLoading(null);
    }
  };
  const upload = async (files: FileList | null, kind: string) => {
    if (!files) return;
    for (const f of Array.from(files)) {
      const d = await api.upload(f, kind);
      if (d.doc_id) setWs((w) => ({ ...w, docs: [...w.docs.filter((x) => x.doc_id !== d.doc_id), d as DocInfo] }));
    }
  };

  return (
    <EvidenceProvider>
      <div className="shell">
        <header className="topbar">
          <button className="btn btn-ghost nav-toggle" onClick={() => setNavOpen(!navOpen)} aria-label="Menu">☰</button>
          <a className="brand" href="#overview"><Logo /><span>Keystone</span></a>
          <span className="tagline">Procurement specialists Amber can rely on</span>
          <div className="topbar-right">
            {health?.ok ? (
              <>
                <Badge tone="info">primary · {health.model}</Badge>
                <Badge tone="muted">verifier · {health.verifier_model}</Badge>
                {!health.api_key_configured && <Badge tone="bad">no API key</Badge>}
              </>
            ) : health ? <Badge tone="bad">API offline</Badge> : null}
          </div>
        </header>
        <aside className={`sidebar ${navOpen ? "open" : ""}`}>
          <nav>
            {NAV.map(([k, l]) => (
              <a key={k} href={`#${k}`} className={route === k ? "active" : ""} onClick={() => go(k)}>{l}</a>
            ))}
          </nav>
          <div className="ws">
            <div className="eyebrow">Workspace</div>
            <div className="ws-buttons">
              <button className="btn btn-ghost small" disabled={!!loading} onClick={() => load("project_alpha")}>{loading === "project_alpha" ? "Loading…" : "Load Project Alpha"}</button>
              <button className="btn btn-ghost small" disabled={!!loading} onClick={() => load("project_beta")}>{loading === "project_beta" ? "Loading…" : "Load Project Beta"}</button>
            </div>
            {ws.sample && <div className="small muted">{ws.sample.project_info?.name ?? ws.sample.project}</div>}
            <ul className="doclist">
              {ws.docs.map((d) => (
                <li key={d.doc_id} title={d.doc_id}><Badge tone="muted">{d.kind}</Badge> {d.name}</li>
              ))}
            </ul>
            <details className="upload">
              <summary>Upload your own PDFs</summary>
              {["spec", "submittal", "bid"].map((k) => (
                <label key={k} className="field small">
                  <span>as {k}</span>
                  <input type="file" accept=".pdf,.txt,.md" multiple onChange={(e) => upload(e.target.files, k)} />
                </label>
              ))}
            </details>
          </div>
        </aside>
        <main className="main">
          {route === "overview" && <Overview go={go} load={load} ws={ws} />}
          {route === "pipeline" && <PipelinePage ws={ws} />}
          {route === "compliance" && <CompliancePage ws={ws} />}
          {route === "bids" && <BidsPage ws={ws} />}
          {route === "leadtime" && <LeadTimePage ws={ws} />}
          {route === "schedule" && <SchedulePage ws={ws} />}
          {route === "audit" && <Audit />}
          {route === "connect" && <Connect />}
        </main>
      </div>
    </EvidenceProvider>
  );
}

function Overview({ go, load, ws }: { go: (r: Route) => void; load: (p: string) => Promise<void>; ws: Workspace }) {
  const specialists: [Route, string, string, string][] = [
    ["compliance", "Spec & submittal compliance", "Comply / deviate / missing for every requirement, citing both documents.", "20/20 on dev set"],
    ["bids", "Bid leveling", "Common-scope matrix, hidden exclusions, arithmetic audit, plug-priced award.", "catches the low-bid trap"],
    ["leadtime", "Lead-time forecasting", "P10–P90 ranges from cited market data and real promise-slip history.", "4,124 real shipments"],
    ["schedule", "Schedule & delivery risk", "CPM + Monte Carlo + counterfactuals: which PO really delays the job.", "5,000 scenarios"],
  ];
  return (
    <div className="page overview">
      <section className="hero">
        <div className="eyebrow">Track 03 · Vertical agents for Amber</div>
        <h1>Specialists that show their work.</h1>
        <p className="lede">
          Keystone is a suite of procurement agents for data-center and construction projects. Each one is callable over MCP, returns
          structured JSON, cites the exact page or row behind every answer, and hands the decision to a person when it is not sure.
        </p>
        <div className="hero-cta">
          <button className="btn btn-primary" onClick={async () => { if (!ws.sample) await load("project_alpha"); go("pipeline"); }}>Run the Project Alpha demo →</button>
          <button className="btn btn-ghost" onClick={() => go("connect")}>Connect Amber via MCP</button>
        </div>
      </section>
      <div className="grid4">
        {specialists.map(([r, t, d, k]) => (
          <button key={r} className="spec-card" onClick={() => go(r)}>
            <div className="spec-kicker">{k}</div>
            <div className="spec-title">{t}</div>
            <div className="spec-desc">{d}</div>
            <div className="spec-go">Open →</div>
          </button>
        ))}
      </div>
      <Card title="How trust is built — the model reads and explains; it doesn't get the last word">
        <ol className="trust">
          <li><b>Verified citations.</b> Every quote the model attributes to a document is located in the real PDF text. Quotes that can't be found can't support a verdict.</li>
          <li><b>Symbolic checks.</b> Numbers are re-decided in code with unit conversion (mm→in, kW→tons, kg→lb, °C→°F). Bid totals are re-added. Leveling, CPM and Monte Carlo are plain arithmetic.</li>
          <li><b>A second opinion.</b> A different model family independently re-judges every compliance finding; disagreement lowers confidence.</li>
          <li><b>Calibrated hand-off.</b> Confidence comes from those agreement signals, not the model's self-rating. Low confidence → routed to a human with the reason.</li>
          <li><b>Number-grounded narratives.</b> Any memo or briefing that mentions a number not in the computed facts is rejected and replaced with a template.</li>
          <li><b>Audit trail.</b> Every run is stored with its inputs, outputs and a trace of each model call (model, latency, cost).</li>
        </ol>
      </Card>
    </div>
  );
}

function Audit() {
  const [runs, setRuns] = useState<any[]>([]);
  const [sel, setSel] = useState<AgentResult | null>(null);
  useEffect(() => { api.runs().then(setRuns); }, []);
  return (
    <div className="page">
      <PageIntro title="Audit log" lede="Every specialist run, replayable: inputs, outputs, confidence and each model call." />
      <Card>
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Run</th><th>Agent</th><th>When (UTC)</th><th>Status</th><th>Summary</th><th>Calls</th><th>Cost</th><th>Time</th></tr></thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.run_id} className="clickable" onClick={() => api.run(r.run_id).then(setSel)}>
                  <td className="mono">{r.run_id}</td><td>{r.agent}</td><td className="small">{r.created_at}</td>
                  <td><Badge tone={r.status === "complete" ? "good" : r.status === "error" ? "bad" : "warn"}>{r.status}</Badge></td>
                  <td className="small">{(r.summary || "").slice(0, 140)}</td>
                  <td>{r.usage?.llm_calls}</td><td>${(r.usage?.cost_usd ?? 0).toFixed(4)}</td><td>{r.usage?.wall_time_s}s</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      {sel && (
        <>
          <Card title="Model-call trace">
            <table className="table"><thead><tr><th>#</th><th>Purpose</th><th>Model</th><th>Latency</th><th>Tokens</th><th>Cost</th></tr></thead>
              <tbody>{sel.usage.trace.map((t, i) => <tr key={i}><td>{i + 1}</td><td>{t.purpose}</td><td className="mono small">{t.model}</td><td>{t.cached ? "cache" : `${t.latency_s}s`}</td><td>{t.completion_tokens}</td><td>${t.cost_usd.toFixed(5)}</td></tr>)}</tbody>
            </table>
          </Card>
          {sel.agent === "spec_compliance" ? <ComplianceResult r={sel} /> : sel.agent === "bid_leveling" ? <BidsResult r={sel} /> : sel.agent === "lead_time" ? <LeadTimeResult r={sel} /> : sel.agent === "schedule_risk" ? <ScheduleResult r={sel} /> : <ResultHeader r={sel} />}
        </>
      )}
    </div>
  );
}

function Connect() {
  const origin = location.origin;
  const cfg = JSON.stringify({ mcpServers: { keystone: { command: "uv", args: ["run", "--directory", "/path/to/Ai-hack", "keystone-mcp"] } } }, null, 2);
  return (
    <div className="page">
      <PageIntro title="Connect Amber via MCP" lede="Every specialist is an MCP tool with structured input and the shared keystone/1.0 output envelope." />
      <div className="grid2">
        <Card title="Streamable HTTP (this server)">
          <pre className="json">{`${origin}/mcp/`}</pre>
          <p className="small">Point any MCP client at this URL. Tools: list_specialists, ingest_document, load_sample_project, get_source, check_spec_compliance, level_bids, predict_lead_time, assess_schedule_risk, run_package_pipeline, get_run.</p>
        </Card>
        <Card title="stdio (Claude Desktop / Code, Cursor…)">
          <pre className="json">{cfg}</pre>
        </Card>
      </div>
      <Card title="Output contract (keystone/1.0)">
        <pre className="json">{`{
  "schema_version": "keystone/1.0",
  "agent": "spec_compliance",
  "run_id": "…", "status": "complete | needs_human_review | error",
  "summary": "…",
  "result": { … agent specific … every finding carries evidence[] },
  "confidence": { "score": 0-1, "level": "high|medium|low", "factors": {…} },
  "human_review": { "required": bool, "reasons": [ … ] },
  "usage": { "models": [], "llm_calls": n, "cost_usd": x, "wall_time_s": t, "trace": [ … ] }
}
evidence = { doc_id, doc_name, page, locator, quote, verified, match_score, url }`}</pre>
      </Card>
    </div>
  );
}
