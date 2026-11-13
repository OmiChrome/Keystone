import React, { useMemo, useState } from "react";
import { AgentResult, DocInfo, Sample, money, pct } from "./api";
import { Badge, Card, Cite, ConfBar, JobLog, ResultHeader, Stat, Verdict, useJob } from "./components";

export type Workspace = { sample: Sample | null; docs: DocInfo[] };

const byKind = (ws: Workspace, kind: string) => ws.docs.filter((d) => d.kind === kind);

function DocSelect({ docs, value, onChange, label }: { docs: DocInfo[]; value: string; onChange: (v: string) => void; label: string }) {
  return (
    <label className="field">
      <span>{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">— select —</option>
        {docs.map((d) => (
          <option key={d.doc_id} value={d.doc_id}>{d.name}</option>
        ))}
      </select>
    </label>
  );
}

function NeedDocs({ ws }: { ws: Workspace }) {
  if (ws.docs.length) return null;
  return <div className="empty">Load a sample project or upload documents from the sidebar first.</div>;
}

/* ===================================================================== compliance */

export function CompliancePage({ ws }: { ws: Workspace }) {
  const specs = byKind(ws, "spec"), subs = byKind(ws, "submittal");
  const [spec, setSpec] = useState(""), [sub, setSub] = useState("");
  const s = spec || specs[0]?.doc_id || "", b = sub || subs[0]?.doc_id || "";
  const job = useJob();
  return (
    <div className="page">
      <PageIntro title="Spec & submittal compliance" lede="Line-by-line check of a vendor submittal against the specification. Every verdict cites both documents; numbers are re-checked with unit conversion; a second model family audits every finding." />
      <NeedDocs ws={ws} />
      <Card>
        <div className="form-row">
          <DocSelect docs={specs.length ? specs : ws.docs} value={s} onChange={setSpec} label="Specification" />
          <DocSelect docs={subs.length ? subs : ws.docs} value={b} onChange={setSub} label="Submittal" />
          <button className="btn btn-primary" disabled={!s || !b || job.running} onClick={() => job.run("compliance", { spec_doc_id: s, submittal_doc_id: b })}>
            {job.running ? "Checking…" : "Check compliance"}
          </button>
        </div>
        <JobLog {...job} />
      </Card>
      {job.result && <ComplianceResult r={job.result} />}
    </div>
  );
}

const DECIDER: Record<string, string> = { comply: "", deviate: "", missing: "", unclear: "" };

export function ComplianceResult({ r }: { r: AgentResult }) {
  const res = r.result;
  const [filter, setFilter] = useState<string>("issues");
  const [open, setOpen] = useState<string | null>(null);
  const [showEmail, setShowEmail] = useState(false);
  if (r.status === "error") return <ResultHeader r={r} />;
  const rows = (res.findings as any[]).filter((f) => filter === "all" || (filter === "issues" ? f.verdict !== "comply" : f.needs_human));
  const c = res.counts;
  return (
    <>
      <ResultHeader r={r} />
      <div className="stats">
        <Stat label="Recommended stamp" value={res.recommended_action} tone={res.recommended_action === "Approved" ? "good" : res.recommended_action === "Approved as Noted" ? "warn" : "bad"} />
        <Stat label="Comply" value={c.comply} tone="good" />
        <Stat label="Deviate" value={c.deviate} tone="bad" />
        <Stat label="Missing" value={c.missing} tone="warn" />
        <Stat label="Citations verified" value={pct(res.citation_verification_rate)} sub="quotes found verbatim in the PDFs" />
      </div>
      <Card
        title={`Findings (${rows.length})`}
        actions={
          <>
            <div className="seg">
              {[["issues", "Issues"], ["review", "Needs human"], ["all", "All"]].map(([k, l]) => (
                <button key={k} className={filter === k ? "on" : ""} onClick={() => setFilter(k)}>{l}</button>
              ))}
            </div>
            <button className="btn btn-ghost small" onClick={() => setShowEmail(!showEmail)}>Draft vendor email</button>
          </>
        }
      >
        {showEmail && (
          <div className="email">
            <div className="eyebrow">Draft — requires your approval before sending</div>
            <pre>{res.review_comments?.draft_email}</pre>
            <button className="btn btn-ghost small" onClick={() => navigator.clipboard.writeText(res.review_comments?.draft_email ?? "")}>Copy</button>
          </div>
        )}
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Ref</th><th>Requirement</th><th>Verdict</th><th>Offered</th><th>Rule check</th><th>2nd model</th><th>Evidence</th><th>Confidence</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((f) => (
                <React.Fragment key={f.req_id}>
                  <tr className={`clickable ${f.needs_human ? "row-flag" : ""}`} onClick={() => setOpen(open === f.req_id ? null : f.req_id)}>
                    <td className="mono">{f.ref}</td>
                    <td>
                      <div className="strong">{f.title}</div>
                      <div className="muted small">{f.requirement}</div>
                    </td>
                    <td><Verdict v={f.verdict} />{f.criticality === "critical" && f.verdict !== "comply" && <Badge tone="bad">critical</Badge>}</td>
                    <td className="small">{f.offered?.value != null ? `${f.offered.value} ${f.offered.unit ?? ""}` : f.offered?.text || "—"}</td>
                    <td className="small">{f.rule_check.status === "n/a" ? <span className="muted">qualitative</span> : <Verdict v={f.rule_check.status} />}</td>
                    <td className="small">{f.verifier ? (f.verifier.agrees ? <Badge tone="good">agrees</Badge> : f.verifier.agrees === false ? <Badge tone="bad">disagrees</Badge> : <Badge tone="muted">n/a</Badge>) : "—"}</td>
                    <td onClick={(e) => e.stopPropagation()} className="cites">
                      <Cite ev={f.evidence.spec} label={`spec p${f.evidence.spec.page ?? "?"}`} />
                      {f.evidence.submittal && <Cite ev={f.evidence.submittal} label={`submittal p${f.evidence.submittal.page ?? "?"}`} />}
                    </td>
                    <td><ConfBar c={f.confidence} /></td>
                  </tr>
                  {open === f.req_id && (
                    <tr className="detail">
                      <td colSpan={8}>
                        <div className="detail-grid">
                          <div>
                            <div className="eyebrow">How this was decided</div>
                            <ul className="decided">
                              <li><b>{f.model_verdict}</b> — primary model reading of the submittal</li>
                              {f.rule_check.status !== "n/a" && <li><b>{f.rule_check.status}</b> — symbolic rule check: {f.rule_check.explanation}</li>}
                              {f.verifier && <li><b>{f.verifier.verdict ?? "n/a"}</b> — {f.verifier.model}: {f.verifier.note}</li>}
                              <li>Final: <b>{f.verdict}</b>{f.needs_human ? " → routed to a human" : ""}</li>
                            </ul>
                            <p className="small">{f.reasoning}</p>
                            {f.review_reasons.length > 0 && <div className="handoff small">{f.review_reasons.join("; ")}</div>}
                          </div>
                          <div>
                            <div className="eyebrow">Spec says</div>
                            <blockquote className="quote small">{f.evidence.spec.quote}</blockquote>
                            <div className="eyebrow">Submittal says</div>
                            <blockquote className="quote small">{f.evidence.submittal?.quote || "— not addressed —"}</blockquote>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}

/* ===================================================================== bids */

export function BidsPage({ ws }: { ws: Workspace }) {
  const bids = byKind(ws, "bid");
  const [sel, setSel] = useState<string[] | null>(null);
  const chosen = sel ?? bids.map((b) => b.doc_id);
  const [useScope, setUseScope] = useState(true);
  const job = useJob();
  const scope = ws.sample?.scope_checklist;
  return (
    <div className="page">
      <PageIntro title="Bid leveling" lede="Lines bids up on a common scope, catches exclusions and arithmetic errors, plugs missing scope at the median of what other bidders charged, and recommends an award with reasons an estimator would trust." />
      <NeedDocs ws={ws} />
      <Card>
        <div className="checks">
          {(bids.length ? bids : ws.docs).map((d) => (
            <label key={d.doc_id} className="check">
              <input type="checkbox" checked={chosen.includes(d.doc_id)} onChange={(e) => setSel(e.target.checked ? [...chosen, d.doc_id] : chosen.filter((x) => x !== d.doc_id))} />
              {d.name}
            </label>
          ))}
        </div>
        {scope && (
          <label className="check">
            <input type="checkbox" checked={useScope} onChange={(e) => setUseScope(e.target.checked)} /> Use the project's scope checklist ({scope.length} items) — otherwise the agent derives one
          </label>
        )}
        <div className="form-row">
          <button className="btn btn-primary" disabled={chosen.length < 2 || job.running} onClick={() => job.run("bids", { bid_doc_ids: chosen, scope: useScope ? scope : null })}>
            {job.running ? "Leveling…" : `Level ${chosen.length} bids`}
          </button>
        </div>
        <JobLog {...job} />
      </Card>
      {job.result && <BidsResult r={job.result} />}
    </div>
  );
}

export function BidsResult({ r }: { r: AgentResult }) {
  if (r.status === "error") return <ResultHeader r={r} />;
  const res = r.result;
  const max = Math.max(...res.ranking.map((x: any) => Math.max(x.leveled_total, x.stated_total ?? 0)));
  const bidders: string[] = res.bids.map((b: any) => b.bidder);
  return (
    <>
      <ResultHeader r={r} />
      <div className="grid2">
        <Card title="Stated vs leveled total">
          <div className="bars">
            {res.ranking.map((x: any) => (
              <div key={x.bidder} className="barrow">
                <div className="barlabel">
                  <span className="strong">#{x.rank} {x.bidder}</span>
                  {x.rank === 1 && <Badge tone="good">recommended</Badge>}
                </div>
                <div className="bartrack">
                  <div className="bar bar-stated" style={{ width: `${(100 * (x.stated_total ?? 0)) / max}%` }}><span>{money(x.stated_total)} stated</span></div>
                  <div className="bar bar-leveled" style={{ width: `${(100 * x.leveled_total) / max}%` }}><span>{money(x.leveled_total)} leveled</span></div>
                </div>
                {x.risks.length > 0 && <ul className="risks">{x.risks.map((k: string, i: number) => <li key={i}>{k}</li>)}</ul>}
              </div>
            ))}
          </div>
          {res.recommendation.ranking_changed_by_leveling && <div className="callout">Leveling changed the winner: the lowest stated bid is not the lowest once missing scope is priced in.</div>}
        </Card>
        <Card title="Award memo">
          <p>{res.recommendation.memo.text}</p>
          <div className="muted small">
            Narrative source: {res.recommendation.memo.source} · numeric grounding check: {res.recommendation.memo.grounding_check}
          </div>
        </Card>
      </div>
      <Card title="Scope matrix">
        <div className="table-wrap">
          <table className="table matrix">
            <thead>
              <tr><th>Scope item</th>{bidders.map((b) => <th key={b}>{b}</th>)}</tr>
            </thead>
            <tbody>
              {res.scope.map((item: string) => (
                <tr key={item}>
                  <td>{item}</td>
                  {res.bids.map((b: any) => {
                    const cell = b.scope[item];
                    const plug = b.leveling.plugs.find((p: any) => p.item === item);
                    const gap = b.leveling.unpriced_gaps.find((p: any) => p.item === item);
                    return (
                      <td key={b.bidder} className={`cell-${cell.status}`}>
                        <Verdict v={cell.status} /> {cell.price ? <span className="small">{money(cell.price)}</span> : null}
                        {plug && <div className="small plug" title={plug.basis}>+ plug {money(plug.amount)}</div>}
                        {gap && <div className="small warn-text" title={gap.reason}>unpriced gap</div>}
                        {cell.evidence && <div><Cite ev={cell.evidence} label="source" /></div>}
                      </td>
                    );
                  })}
                </tr>
              ))}
              <tr className="totals">
                <td>Stated total</td>
                {res.bids.map((b: any) => <td key={b.bidder}>{money(b.stated_total)}{b.arithmetic_error && <div className="small bad-text">line items sum to {money(b.arithmetic_error.sum_of_line_items)}</div>}</td>)}
              </tr>
              <tr className="totals">
                <td>Plugs</td>
                {res.bids.map((b: any) => <td key={b.bidder}>{money(b.leveling.plug_total)}</td>)}
              </tr>
              <tr className="totals strong">
                <td>Leveled total</td>
                {res.bids.map((b: any) => <td key={b.bidder}>{money(b.leveling.leveled_total)}</td>)}
              </tr>
            </tbody>
          </table>
        </div>
      </Card>
      <div className="grid3">
        {res.bids.map((b: any) => (
          <Card key={b.bidder} title={b.bidder}>
            <div className="small muted">Lead time {b.lead_time_weeks ?? "—"} wks · validity {b.validity_days ?? "—"} days · warranty {b.warranty?.months ?? "—"} months</div>
            <div className="eyebrow">Exclusions</div>
            <ul className="small">{b.exclusions.length ? b.exclusions.map((x: any, i: number) => <li key={i}>{x.text} <Cite ev={x.evidence} label="↗" /></li>) : <li className="muted">none</li>}</ul>
            <div className="eyebrow">Qualifications</div>
            <ul className="small">{b.qualifications.length ? b.qualifications.map((x: any, i: number) => <li key={i}><Badge tone={x.risk === "high" ? "bad" : x.risk === "medium" ? "warn" : "muted"}>{x.risk}</Badge> {x.text} <Cite ev={x.evidence} label="↗" /></li>) : <li className="muted">none</li>}</ul>
          </Card>
        ))}
      </div>
    </>
  );
}

/* ===================================================================== lead time */

function parseCsv(csv: string): Record<string, string>[] {
  const [h, ...rows] = csv.trim().split(/\r?\n/);
  const cols = h.split(",");
  return rows.map((r) => {
    const out: string[] = [];
    let cur = "", q = false;
    for (const ch of r) {
      if (ch === '"') q = !q;
      else if (ch === "," && !q) { out.push(cur); cur = ""; }
      else cur += ch;
    }
    out.push(cur);
    return Object.fromEntries(cols.map((c, i) => [c, out[i] ?? ""]));
  });
}

export function LeadTimePage({ ws }: { ws: Workspace }) {
  const initial = useMemo(() => {
    if (!ws.sample?.purchase_orders_csv) return [{ item_id: "ITEM-1", description: "480V switchgear lineup, 4000 A", quoted_lead_weeks: "36", order_date: "2026-12-01", need_by_date: "2027-09-01", shipment_mode: "Truck" }];
    return parseCsv(ws.sample.purchase_orders_csv).map((r) => ({ item_id: r.po_number, description: r.item, quoted_lead_weeks: r.quoted_lead_weeks, order_date: r.order_date, need_by_date: "", shipment_mode: r.shipment_mode, vendor: r.vendor, promised_date: r.promised_date }));
  }, [ws.sample]);
  const [items, setItems] = useState<any[] | null>(null);
  const rows = items ?? initial;
  const job = useJob();
  const set = (i: number, k: string, v: string) => setItems(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  return (
    <div className="page">
      <PageIntro title="Lead-time forecasting" lede="Honest ranges, not single guesses: published market lead times (every number cited) blended with how reliably suppliers hit their promised dates in 4,124 real shipments (USAID SCMS public data)." />
      <Card>
        <div className="table-wrap">
          <table className="table edit">
            <thead><tr><th>ID</th><th>Description</th><th>Quoted wks</th><th>Order date</th><th>Need by</th><th>Mode</th><th /></tr></thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  {["item_id", "description", "quoted_lead_weeks", "order_date", "need_by_date", "shipment_mode"].map((k) => (
                    <td key={k}><input value={r[k] ?? ""} onChange={(e) => set(i, k, e.target.value)} placeholder={k === "need_by_date" ? "YYYY-MM-DD" : ""} /></td>
                  ))}
                  <td><button className="btn btn-ghost small" onClick={() => setItems(rows.filter((_, j) => j !== i))}>✕</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="form-row">
          <button className="btn btn-ghost" onClick={() => setItems([...rows, { item_id: `ITEM-${rows.length + 1}`, description: "", quoted_lead_weeks: "", order_date: "", need_by_date: "", shipment_mode: "" }])}>+ Add item</button>
          <button className="btn btn-primary" disabled={job.running} onClick={() => job.run("leadtime", { items: rows.map((r) => ({ ...r, quoted_lead_weeks: r.quoted_lead_weeks ? Number(r.quoted_lead_weeks) : null, need_by_date: r.need_by_date || null, order_date: r.order_date || null, promised_date: r.promised_date || null, shipment_mode: r.shipment_mode || null })) })}>
            {job.running ? "Forecasting…" : "Forecast"}
          </button>
        </div>
        <JobLog {...job} />
      </Card>
      {job.result && <LeadTimeResult r={job.result} />}
    </div>
  );
}

export function RangeBar({ lt, max, marker, markerLabel }: { lt: any; max: number; marker?: number | null; markerLabel?: string }) {
  const x = (v: number) => `${Math.min(100, (100 * v) / max)}%`;
  return (
    <div className="range" title={`P10 ${lt.p10} · P50 ${lt.p50} · P90 ${lt.p90} weeks`}>
      <div className="range-band" style={{ left: x(lt.p10), width: `calc(${x(lt.p90)} - ${x(lt.p10)})` }} />
      <div className="range-mid" style={{ left: x(lt.p50) }} />
      {marker != null && <div className="range-marker" style={{ left: x(marker) }} title={markerLabel}><span>{markerLabel}</span></div>}
    </div>
  );
}

export function LeadTimeResult({ r }: { r: AgentResult }) {
  if (r.status === "error") return <ResultHeader r={r} />;
  const fs = r.result.forecasts as any[];
  const max = Math.max(...fs.map((f) => f.forecast?.lead_time_weeks.p90 ?? 0), ...fs.map((f) => f.forecast?.need_by_weeks_from_order ?? 0)) * 1.08 || 1;
  const cal = r.result.calibration;
  return (
    <>
      <ResultHeader r={r} />
      <Card title="Forecasts (weeks from order)" actions={<span className="small muted">band = P10–P90 · tick = P50 · flag = quote / need-by</span>}>
        {fs.map((f) => (
          <div key={f.item.item_id} className="fc">
            <div className="fc-head">
              <div>
                <span className="strong mono">{f.item.item_id}</span> {f.item.description}
                <div className="small muted">category: {f.reference_class?.label ?? "none"} ({f.category_reason})</div>
              </div>
              <ConfBar c={f.confidence} />
            </div>
            {f.forecast ? (
              <>
                <RangeBar lt={f.forecast.lead_time_weeks} max={max} marker={f.forecast.need_by_weeks_from_order ?? f.item.quoted_lead_weeks} markerLabel={f.forecast.need_by_weeks_from_order ? "need-by" : "quote"} />
                <div className="fc-nums small">
                  <span>P10 <b>{f.forecast.lead_time_weeks.p10}</b></span>
                  <span>P50 <b>{f.forecast.lead_time_weeks.p50}</b></span>
                  <span>P90 <b>{f.forecast.lead_time_weeks.p90}</b> wks</span>
                  {f.forecast.arrival_dates && <span>arrival P50 {f.forecast.arrival_dates.p50} · P90 {f.forecast.arrival_dates.p90}</span>}
                  {f.forecast.p_late_vs_promise != null && <span>P(later than promise) <b>{pct(f.forecast.p_late_vs_promise)}</b></span>}
                  {f.forecast.p_on_time_vs_need_by != null && <span>P(on time for need-by) <b>{pct(f.forecast.p_on_time_vs_need_by)}</b></span>}
                </div>
                <ul className="small drivers">{f.drivers.map((d: string, i: number) => <li key={i}>{d}</li>)}</ul>
                <div className="cites">{f.evidence.map((e: any, i: number) => <a key={i} className="cite cite-ok" href={e.url} target="_blank" rel="noreferrer" title={e.quote}>source {i + 1} ↗</a>)}</div>
              </>
            ) : (
              <div className="handoff small">No forecast — {f.review_reasons.join("; ")}</div>
            )}
          </div>
        ))}
      </Card>
      {cal && (
        <Card title="Is the slip model honest? (chronological back-test on public data)">
          <p className="small">Fit on shipments up to 2012, tested on {cal.n_test} shipments from 2013 on: share of real deliveries that arrived by each predicted quantile.</p>
          <div className="stats">
            {Object.entries(cal.quantiles).map(([k, v]: any) => <Stat key={k} label={`nominal ${k.toUpperCase()}`} value={pct(v.realised_share_on_or_before, 1)} sub={`slip ×${v.predicted_slip_ratio}`} />)}
          </div>
          <p className="small muted">Realised ≥ nominal → conservative. Late-delivery rate fell from {pct(cal.p_late_train, 1)} (fit years) to {pct(cal.p_late_test, 1)} (test years), so the model errs on the cautious side.</p>
        </Card>
      )}
    </>
  );
}

/* ===================================================================== schedule */

export function SchedulePage({ ws }: { ws: Workspace }) {
  const p = ws.sample?.project_info;
  const [sched, setSched] = useState<string | null>(null);
  const [pos, setPos] = useState<string | null>(null);
  const [start, setStart] = useState<string | null>(null);
  const [target, setTarget] = useState<string | null>(null);
  const S = sched ?? ws.sample?.schedule_csv ?? "", P = pos ?? ws.sample?.purchase_orders_csv ?? "";
  const st = start ?? p?.start_date ?? "", tg = target ?? p?.target_completion ?? "";
  const job = useJob();
  return (
    <div className="page">
      <PageIntro title="Schedule & delivery risk" lede="Which late equipment will really hold up the project? Critical-path analysis plus 5,000 simulated delivery scenarios, then a counterfactual for each PO: how much earlier would we finish if it arrived on its need-by date?" />
      <Card>
        <div className="grid2">
          <label className="field"><span>Schedule CSV (activity_id, name, duration_days, predecessors, requires_po)</span><textarea rows={8} value={S} onChange={(e) => setSched(e.target.value)} /></label>
          <label className="field"><span>Purchase orders CSV</span><textarea rows={8} value={P} onChange={(e) => setPos(e.target.value)} /></label>
        </div>
        <div className="form-row">
          <label className="field"><span>Project start</span><input value={st} onChange={(e) => setStart(e.target.value)} placeholder="YYYY-MM-DD" /></label>
          <label className="field"><span>Target completion</span><input value={tg} onChange={(e) => setTarget(e.target.value)} placeholder="YYYY-MM-DD" /></label>
          <button className="btn btn-primary" disabled={!S || !P || !st || job.running} onClick={() => job.run("schedule", { schedule_csv: S, po_csv: P, project_start: st, target_completion: tg || null })}>
            {job.running ? "Simulating…" : "Assess risk"}
          </button>
        </div>
        <JobLog {...job} />
      </Card>
      {job.result && <ScheduleResult r={job.result} />}
    </div>
  );
}

export function ScheduleResult({ r }: { r: AgentResult }) {
  const [cpm, setCpm] = useState(false);
  if (r.status === "error") return <ResultHeader r={r} />;
  const res = r.result, sim = res.simulation;
  const maxDelay = Math.max(1, ...res.risks.map((x: any) => x.expected_project_delay_caused_days));
  return (
    <>
      <ResultHeader r={r} />
      <div className="stats">
        {sim.p_meet_target != null && <Stat label={`P(finish by ${res.target_completion})`} value={pct(sim.p_meet_target)} tone={sim.p_meet_target >= 0.8 ? "good" : sim.p_meet_target >= 0.5 ? "warn" : "bad"} />}
        <Stat label="Finish P50" value={sim.finish_dates.p50} />
        <Stat label="Finish P90" value={sim.finish_dates.p90} />
        <Stat label="Plan without material risk" value={sim.planned_finish_without_material_risk} sub={`${sim.scenarios.toLocaleString()} scenarios`} />
      </div>
      <Card title="Ranked by delay actually caused">
        {res.risks.map((x: any) => (
          <div key={x.po_number} className="risk">
            <div className="risk-head">
              <div>
                <Badge tone={x.severity === "critical" ? "bad" : x.severity === "high" ? "warn" : x.severity === "medium" ? "info" : "muted"}>{x.severity}</Badge>{" "}
                <span className="strong">#{x.rank} {x.po_number}</span> {x.item} <span className="muted small">· {x.vendor} · {x.status}</span>
              </div>
              <ConfBar c={x.confidence} />
            </div>
            <div className="risk-grid">
              <div>
                <div className="small muted">Expected project delay caused</div>
                <div className="delaybar"><div style={{ width: `${(100 * x.expected_project_delay_caused_days) / maxDelay}%` }} /><span>{x.expected_project_delay_caused_days} days</span></div>
              </div>
              <div className="small">
                need-by <b>{x.need_by_date}</b> · promised {x.promised_date} · forecast P50 <b>{x.delivery_forecast.p50}</b> (P90 {x.delivery_forecast.p90}) · P(late) <b>{pct(x.p_late_vs_need_by)}</b>
              </div>
            </div>
            <ul className="small actions">{x.actions.map((a: string, i: number) => <li key={i}>{a}</li>)}</ul>
            <div className="cites">{x.evidence.map((e: any, i: number) => <Cite key={i} ev={e} />)}{x.lead_time_sources.map((e: any, i: number) => <a key={"s" + i} className="cite cite-ok" href={e.url} target="_blank" rel="noreferrer" title={e.quote}>market source {i + 1} ↗</a>)}</div>
          </div>
        ))}
      </Card>
      <Card title="Critical path (deterministic CPM)" actions={<button className="btn btn-ghost small" onClick={() => setCpm(!cpm)}>{cpm ? "Hide" : "Show"}</button>}>
        {cpm && (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>ID</th><th>Activity</th><th>Days</th><th>Early start</th><th>Late start</th><th>Float</th><th>Needs PO</th></tr></thead>
              <tbody>{res.cpm.map((a: any) => <tr key={a.activity_id} className={a.total_float_days <= 0 ? "row-flag" : ""}><td className="mono">{a.activity_id}</td><td>{a.name}</td><td>{a.duration_days}</td><td>{a.early_start}</td><td>{a.late_start}</td><td>{a.total_float_days}</td><td>{a.requires_po.join(", ")}</td></tr>)}</tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}

/* ===================================================================== pipeline */

export function PipelinePage({ ws }: { ws: Workspace }) {
  const job = useJob();
  const s = ws.sample;
  const ready = !!(s && byKind(ws, "bid").length >= 2 && byKind(ws, "spec").length && byKind(ws, "submittal").length && s.schedule_csv);
  const runIt = () =>
    job.run("pipeline", {
      bid_doc_ids: byKind(ws, "bid").map((d) => d.doc_id),
      spec_doc_id: byKind(ws, "spec")[0].doc_id,
      submittal_doc_id: byKind(ws, "submittal")[0].doc_id,
      schedule_csv: s!.schedule_csv,
      po_csv: s!.purchase_orders_csv,
      package_po: "PO-1001",
      project_start: s!.project_info?.start_date,
      target_completion: s!.project_info?.target_completion,
      scope: s!.scope_checklist,
    });
  const r = job.result;
  return (
    <div className="page">
      <PageIntro title="Package pipeline" lede="The specialists working as one product: level the bids → check the winner's submittal → feed its lead time into the schedule → one award decision with conditions and a full hand-off trail." />
      <Card>
        <div className="flow">
          {["Bid leveling", "Spec compliance", "Lead time", "Schedule risk", "Decision"].map((s, i) => (
            <React.Fragment key={s}>
              {i > 0 && <span className="flow-arrow">→</span>}
              <span className="flow-step">{s}</span>
            </React.Fragment>
          ))}
        </div>
        {!ready && <div className="empty">Load sample “Project Alpha” (sidebar) — it has bids, spec, submittal, schedule and POs for the 480 V switchgear package (PO-1001).</div>}
        <div className="form-row">
          <button className="btn btn-primary" disabled={!ready || job.running} onClick={runIt}>{job.running ? "Running pipeline…" : "Run package pipeline"}</button>
        </div>
        <JobLog {...job} />
      </Card>
      {r && r.status !== "error" && (
        <>
          <ResultHeader r={r} />
          <Card title={`Decision: ${r.result.decision} — ${r.result.vendor}`}>
            <ol className="conditions">{r.result.conditions.map((c: string, i: number) => <li key={i}>{c}</li>)}</ol>
          </Card>
          <Card title="Hand-off trail">
            <ol className="trail">
              {r.result.trail.map((t: any) => (
                <li key={t.step}>
                  <div className="strong">{t.step}. {t.agent}</div>
                  <div className="small">{t.output}</div>
                  <pre className="json small">{JSON.stringify(t.handoff, null, 1)}</pre>
                </li>
              ))}
            </ol>
          </Card>
          <h2 className="section-title">Step details</h2>
          <BidsResult r={r.result.steps.bid_leveling} />
          <ComplianceResult r={r.result.steps.spec_compliance} />
          <ScheduleResult r={r.result.steps.schedule_risk} />
        </>
      )}
      {r && r.status === "error" && <ResultHeader r={r} />}
    </div>
  );
}

export function PageIntro({ title, lede }: { title: string; lede: string }) {
  return (
    <header className="page-intro">
      <h1>{title}</h1>
      <p>{lede}</p>
    </header>
  );
}
