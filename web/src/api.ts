export type Evidence = {
  doc_id: string;
  doc_name: string;
  page: number | null;
  locator: string | null;
  quote: string;
  verified: boolean;
  match_score: number;
  url?: string | null;
};

export type Confidence = { score: number; level: "high" | "medium" | "low"; factors: Record<string, number>; rationale: string };

export type AgentResult = {
  schema_version: string;
  agent: string;
  run_id: string;
  created_at: string;
  status: "complete" | "needs_human_review" | "error";
  summary: string;
  result: any;
  confidence: Confidence;
  human_review: { required: boolean; reasons: string[] };
  usage: {
    models: string[];
    llm_calls: number;
    cached_calls: number;
    cost_usd: number;
    wall_time_s: number;
    llm_latency_s: number;
    prompt_tokens: number;
    completion_tokens: number;
    trace: { purpose: string; model: string; cached: boolean; latency_s: number; completion_tokens: number; cost_usd: number }[];
  };
  inputs: Record<string, unknown>;
};

export type DocInfo = { doc_id: string; name: string; kind: string; n_pages: number };

export type Sample = {
  project: string;
  docs: Record<string, DocInfo>;
  schedule_csv?: string;
  purchase_orders_csv?: string;
  project_info?: { name: string; start_date: string; target_completion: string };
  scope_checklist?: string[];
};

export type JobEvent = { t: number; event: string; purpose?: string; model?: string; cached?: boolean; latency_s?: number; status?: number; tokens?: number };
export type Job = { job_id: string; kind: string; status: "running" | "done" | "error"; elapsed_s: number; events: JobEvent[]; n_events: number; result: AgentResult | null; error: string | null };

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json() as Promise<T>;
}

export const api = {
  health: () => fetch("/api/health").then(j<any>),
  loadSample: (p: string) => fetch(`/api/samples/${p}`, { method: "POST" }).then(j<Sample>),
  doc: (id: string, page?: number) => fetch(`/api/documents/${id}${page ? `?page=${page}` : ""}`).then(j<any>),
  upload: (f: File, kind: string) => {
    const fd = new FormData();
    fd.append("file", f);
    fd.append("kind", kind);
    return fetch("/api/documents", { method: "POST", body: fd }).then(j<any>);
  },
  start: (path: string, body: unknown) =>
    fetch(`/api/${path}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }).then(j<{ job_id: string }>),
  job: (id: string, since: number) => fetch(`/api/jobs/${id}?since=${since}`).then(j<Job>),
  runs: () => fetch("/api/runs").then(j<any[]>),
  run: (id: string) => fetch(`/api/runs/${id}`).then(j<AgentResult>),
};

export const money = (v: number | null | undefined) =>
  v == null ? "—" : v.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
export const pct = (v: number | null | undefined, d = 0) => (v == null ? "—" : `${(100 * v).toFixed(d)}%`);
