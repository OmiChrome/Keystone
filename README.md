# Keystone — procurement specialists Amber can rely on

**Track 03 · Vertical Agents (Amber sub-agents)** — Kaya AI Grand Challenge, "The Dawn of Superintelligence".

Keystone is a suite of specialist procurement agents for data-center and construction projects. Each specialist:

- is **callable by another agent** over **MCP** (stdio or streamable HTTP) and REST,
- takes **structured input** and returns the shared **`keystone/1.0` JSON envelope**,
- **cites its sources** for every answer (document + page / CSV row / published URL, with the verbatim quote),
- gives a **confidence score built from verification signals** (not the model's self-rating) and **hands off to a human** when unsure,
- **refuses to make things up**: quotes that can't be found in the source can't support a verdict, numbers in narratives must exist in the computed facts, unknown equipment gets no forecast.

| Specialist | What it does | How it goes deeper than an API call |
|---|---|---|
| `spec_compliance` | Submittal vs. spec, line by line: comply / deviate / missing / unclear | LLM extracts requirements → evidence-grounded review → **quote verification** against PDF text → **symbolic unit-converted rule check** (mm→in, kW→tons, kg→lb, °C→°F) → **independent second model family** re-judges every finding → calibrated confidence; draft vendor comments |
| `bid_leveling` | Scope matrix, exclusions, qualifications, award recommendation | Per-bid extraction with verified quotes → **arithmetic audit** (re-adds line items) → **plug pricing** of missing scope at the median other bidders charged → ranking → memo with a **numeric grounding guard** |
| `lead_time` | P10/P50/P80/P90 lead time + arrival dates, P(on time) | **Reference classes from 2025–26 published market data** (every number cited) × **empirical supplier promise-slip distribution learned from 4,124 real shipments** (USAID SCMS) → Monte Carlo; quotes below market are treated sceptically |
| `schedule_risk` | Which late equipment will really delay the project, and what to do | **CPM** forward/backward pass → need-by dates → **5,000-scenario Monte Carlo** through the network → **counterfactual attribution** (delay each PO actually causes) → rule-based actions |
| `package_pipeline` | The suite as one product | bids → recommended vendor → compliance on its submittal → its lead time fed into the schedule → award decision with conditions and a hand-off trail |

> Design principle (also what won START Hack 2026's procurement challenge): **the model reads and explains; code decides.**
> Every arithmetic, unit, ranking and scheduling decision is deterministic and auditable.

---

## Quick start

Requirements: [uv](https://docs.astral.sh/uv/) and [Bun](https://bun.sh). Python 3.13 is fetched by uv.

```bash
cp .env.example .env        # put your OpenAI-compatible API key in KEYSTONE_LLM_API_KEY
./run.sh                    # uv sync + bun build + sample data + server
```

Open <http://127.0.0.1:8000>, click **Run the Project Alpha demo**. Everything is also available headless:

```bash
uv run keystone demo project_alpha      # full package pipeline, JSON to stdout
uv run keystone eval                    # accuracy vs hand-labelled ground truth -> eval/REPORT.md
uv run pytest                           # offline tests (no API key needed)
```

### Deploy (Vercel)

The repo deploys to Vercel as-is: `app.py` is the FastAPI entrypoint, dependencies come from `pyproject.toml` + `uv.lock`,
`scripts/build_web.py` builds the UI with Bun during the Vercel build, and `vercel.json` gives the function 300 s.

1. vercel.com → **Add New… → Project** → import this GitHub repo (framework preset: FastAPI is auto-detected).
2. **Settings → Environment Variables**: `KEYSTONE_LLM_API_KEY` (required for new documents; the bundled demo replays from `demo_cache/` without it).
   Optional: `KEYSTONE_MODEL`, `KEYSTONE_VERIFIER_MODEL`, `KEYSTONE_FALLBACK_MODELS`, `KEYSTONE_LLM_BASE_URL`.
3. Deploy. After that every push deploys automatically (pushes to `main` → production, other branches → preview URLs).

On Vercel (`VERCEL` env set) Keystone runs in serverless mode: specialist jobs run inside the request (no background threads),
the audit log lives in `/tmp` per instance, MCP over HTTP is stateless (`/mcp/`), and sample documents are re-ingested on cold starts.
Uploaded PDFs may need re-uploading if a request lands on a fresh instance; for long uncached runs (> 300 s) or persistent
uploads, run the same app on any container host with `./run.sh`.

### Connect Amber (MCP)

```jsonc
// stdio - Claude Desktop / Claude Code / Cursor / any MCP host
{ "mcpServers": { "keystone": { "command": "uv", "args": ["run", "--directory", "/path/to/Ai-hack", "keystone-mcp"] } } }
```

Streamable HTTP: `http://127.0.0.1:8000/mcp/` (served by `keystone serve`), or standalone `uv run keystone-mcp --http --port 8765`.

Tools: `list_specialists`, `ingest_document`, `load_sample_project`, `get_source`, `check_spec_compliance`, `level_bids`,
`predict_lead_time`, `assess_schedule_risk`, `run_package_pipeline`, `get_run`. Smoke test: `uv run python scripts/mcp_smoke.py [--http URL]`.

---

## The shared contract (`keystone/1.0`)

```jsonc
{
  "schema_version": "keystone/1.0", "agent": "spec_compliance", "run_id": "…", "created_at": "…",
  "status": "complete | needs_human_review | error",
  "summary": "20 requirements checked: 10 comply, 8 deviate, 2 missing …",
  "result": { /* agent-specific; every finding carries evidence */ },
  "confidence": { "score": 0.0-1.0, "level": "high|medium|low", "factors": { "submittal_citation": 1, "rule_check": 1, "cross_model": 1, … } },
  "human_review": { "required": true, "reasons": ["2.3.E: rule check says deviate (6400 mm = 252 in > 240 in) but model said comply"] },
  "usage": { "models": [], "llm_calls": 8, "cached_calls": 0, "cost_usd": 0.0057, "wall_time_s": 74, "trace": [ /* every model call */ ] }
}
// evidence (same everywhere)
{ "doc_id": "…", "doc_name": "submittal_voltara_swg1.pdf", "page": 1, "locator": "2.2.C | row 4",
  "quote": "50 kA RMS symmetrical at 480 V", "verified": true, "match_score": 100, "url": null }
```

Shared domain object `EquipmentItem` flows between specialists (bid → submittal → PO → delivery). The pipeline passes the
recommended bidder's quoted lead time straight into the schedule-risk PO table.

### How confidence is computed (spec compliance)

Weighted agreement of independent signals — spec quote verified (0.15), submittal quote verified (0.25), symbolic rule check agrees (0.25),
second model family agrees (0.25), model's own certainty (0.10, deliberately low weight: in testing DeepSeek returned
`"confidence": 338` on a 0-1 scale). Any failed signal caps the score at 0.55; below 0.7 or `unclear` → human review.

---

## Accuracy (hand-labelled ground truth)

`uv run keystone eval` → [`eval/REPORT.md`](eval/REPORT.md), [`eval/results.json`](eval/results.json).

- **dev** = Project Alpha (480 V switchgear) — used while writing prompts.
- **held-out** = Project Beta (air-cooled chillers) — a different equipment class, units (kW vs tons, kg vs lb, °C vs °F, dBA at a different distance), and documents never used while writing prompts.

| Split | Specialist | Result |
|---|---|---|
| dev (Alpha) | spec_compliance | **20/20** requirements exact · issue recall 100% · false issues 0 · citations verified 100% |
| held-out (Beta) | spec_compliance | first run **15/16** — the single miss had confidence 0.50 and was **routed to a human**, not auto-decided (all 15 high-confidence findings correct) |
| held-out (Beta) | spec_compliance, after fix | **16/16** · escalation 6% (the 1 finding where rule check and models disagree) · auto-decided accuracy 100% |
| dev (Alpha) | bid_leveling | scope matrix **36/36** cells · arithmetic error found (Helix: items sum $1,004,500 vs stated $991,500) · quotes verified 98.8% |
| held-out (Beta) | bid_leveling | scope matrix **18/18** cells · no false arithmetic alarms · quotes verified 100% |

The held-out miss was instructive and is kept in [`eval/results_before_fix.json`](eval/results_before_fix.json): the spec required
"5 years parts **and labor**", the vendor offered "5 years parts only; labor … first year". Both models said *deviate*, but the numeric
rule check (5 yr ≥ 5 yr) overrode them. Fix (general, not data-specific): a failed numeric check is *sufficient* for a deviation but a
passing one is only *necessary* for compliance — arithmetic may downgrade a verdict, never upgrade it (`test_rule_check_never_upgrades_a_deviation`).
Note this means the post-fix held-out number is no longer strictly blind.

Hallucination check: across both projects every compliance citation and 99% of bid citations were found verbatim in the source
PDFs; the remaining bid quote was flagged `verified: false` in the output rather than silently trusted.

Lead-time honesty: the promise-slip model is back-tested chronologically on public data (fit ≤ 2012, test ≥ 2013, n = 1,584):
deliveries arrived by the predicted P50/P80/P90 date 95.8% of the time and by P95 99.1% — i.e. **conservative**, because suppliers
got more reliable over time (late rate 7.4% → 4.2%). We report this rather than claim calibration.

---

## Models, cost and speed

| Role | Default model | Notes |
|---|---|---|
| Primary reader/extractor | `DeepSeek-V4.1-Flash` | JSON mode; `reasoning_effort=medium` for compliance review |
| Independent verifier | `Gemma-4-31B-IT` | different model family by design; never falls back to the primary family |
| Fallback chain | Gemma → Qwen3.8-27B → DeepSeek-V4-Flash → MiniCPM-V-4.7-35B | used automatically on 429/5xx/timeouts; the model that actually answered is recorded |

All served through AMD TokenLab (OpenAI-compatible). Typical uncached runs on the sample projects:

| Specialist | LLM calls | Cost / run | Wall time |
|---|---|---|---|
| spec_compliance (20 requirements) | ~8 | ≈ $0.006 | 40 s – 3 min (provider load) |
| bid_leveling (3 bids) | 4 | ≈ $0.002 | 30 s – 2 min |
| lead_time | 0–1 | $0 | < 1 s |
| schedule_risk (5 POs, 5,000 scenarios) | 1 (briefing) | < $0.001 | 1–10 s |
| package_pipeline | ~13 | ≈ $0.01 | 2–5 min |

Responses are cached on disk in `demo_cache/` (`KEYSTONE_CACHE=1`) so demos replay instantly and identically; set `0` to force fresh calls.
The client respects the provider's rate limit (`KEYSTONE_RPM`, default 18/min).

### Private / offline deployment

Every model above is open-weight. Point Keystone at a local OpenAI-compatible server and nothing leaves the machine:

```bash
# e.g. vLLM or Ollama on a GPU workstation
KEYSTONE_LLM_BASE_URL=http://localhost:11434/v1 KEYSTONE_MODEL=gemma4:31b KEYSTONE_VERIFIER_MODEL=qwen3:32b \
KEYSTONE_FALLBACK_MODELS= ./run.sh
```

Lead-time and schedule-risk math run fully offline already (no LLM needed).

---

## Data — where everything came from

| Data | Source | Notes |
|---|---|---|
| Sample projects (`samples/`) | **Synthetic, written by us** (`samples/generate.py`) | All companies, products and model numbers are **fictional** and labelled "(fictional)". Ratings/standards (UL 1558, ANSI C12.20, NEC 240.87, AHRI 550/590…) are realistic. Ground truth hand-labelled in `ground_truth.json`. |
| Market lead-time reference classes | Published 2025–26 sources — Wood Mackenzie survey (as reported by POWER, EEPower), Reuters/Kitco, Linesight CMI 2026, IndustrialSage, Hourigan, iRecruit, Bisnow | `src/keystone/data/leadtime_reference.json`, every range links to its source. Ranges are our reading of those figures (low/high ≈ P10/P90). |
| Supplier promise reliability | **USAID SCMS Supply Chain Shipment Pricing Data** (10,324 shipments 2006-2015; public mirror, SHA-256 verified) | `scripts/build_promise_model.py` downloads, verifies and reduces it to `promise_reliability.json`. Only aggregates are committed. Attribution: USAID Development Data Library. Caveat: health commodities, not construction equipment — used only for the *shape* of slip past a promised date. |

No confidential client data is used.

---

## Architecture

```
web/ (React + TypeScript, bundled by Bun)  ──REST──┐
Amber / any MCP host ───────── MCP (stdio|HTTP) ───┤
                                                   ▼
                       keystone.service  (one facade for MCP + REST)
          ┌──────────────┬───────────────┬──────────────┬───────────────┐
   spec_compliance   bid_leveling     lead_time      schedule_risk   package_pipeline
          │               │               │               │
   docs.py (PDF→pages, quote verification, BM25)   units.py (symbolic checks)   grounding.py (number guard)
   llm.py (OpenAI-compatible: rate limit, cache, retries, model fallback, JSON repair, usage trace)
   runs/results/*.json  ← every run persisted (audit log, replay in the UI)
```

Repository layout: `src/keystone/` (agents, MCP server, API, CLI), `web/` (UI), `samples/` (synthetic projects + labels), `docs/` (competitor research, demo script, deck outline),
`scripts/` (data build, MCP smoke test), `tests/` (offline tests), `eval/` (accuracy report).

## Known limitations (honest list)

- Spec/submittal PDFs are read as text (pdfplumber). Scanned drawings would need OCR / a vision model (the client already supports image inputs).
- Lead-time reference classes come from trade press, not OEM order books; replace with your own PO history for production use.
- The promise-slip prior comes from a non-construction public dataset; it is the best public evidence we found of real promise-vs-delivery behaviour.
- Ground-truth sets are small (36 compliance requirements, 63 bid scope cells); they show behaviour, not statistical significance.
- The shared TokenLab endpoint is sometimes overloaded; Keystone degrades (fallback models, un-verified findings flagged) rather than failing, but latency varies.
