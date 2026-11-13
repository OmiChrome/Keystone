"""Offline tests: no network, no API key. LLM calls are mocked where an agent needs them."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ALPHA = ROOT / "samples" / "project_alpha"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("KEYSTONE_RUNS_DIR", str(tmp_path / "runs"))
    import keystone.config as cfg
    import keystone.docs as docs

    object.__setattr__(cfg.settings, "runs_dir", tmp_path / "runs")
    object.__setattr__(cfg.settings, "cache", False)
    docs._store = None
    yield


# ------------------------------------------------------------------------------------------ units


def test_unit_conversions_and_comparators():
    from keystone.units import compare

    assert compare({"comparator": "<=", "value": 240, "unit": "in"}, {"value": 6400, "unit": "mm"}).status == "deviate"  # 252 in
    assert compare({"comparator": ">=", "value": 500, "unit": "tons"}, {"value": 1700, "unit": "kW"}).status == "deviate"  # 483 t
    assert compare({"comparator": "<=", "value": 30000, "unit": "lb"}, {"value": 13600, "unit": "kg"}).status == "comply"  # 29,983 lb
    assert compare({"comparator": ">=", "value": 125, "unit": "deg F"}, {"value": 52, "unit": "°C"}).status == "comply"  # 125.6 F
    assert compare({"comparator": ">=", "value": 65, "unit": "kA"}, {"value": 50, "unit": "kA"}).status == "deviate"
    assert compare({"comparator": ">=", "value": 4000, "unit": "A"}, {"value": 4, "unit": "kA"}).status == "comply"
    assert compare({"comparator": "text"}, {"value": None}).status == "n/a"
    assert compare({"comparator": ">=", "value": 65, "unit": "kA"}, {"value": None}).status == "unknown"
    assert compare({"comparator": ">=", "value": 65, "unit": "kA"}, {"value": 65, "unit": "V"}).status == "unknown"


# ---------------------------------------------------------------------------------- documents


def test_quote_verification_rejects_invented_quotes():
    from keystone.docs import make_evidence, store

    d = store().ingest_path(ALPHA / "submittal_voltara_swg1.pdf", "submittal")
    ok = make_evidence(d, "50 kA RMS symmetrical at 480 V")
    assert ok.verified and ok.page == 1
    moved = make_evidence(d, "Integral SPD, UL 1449 4th Edition listed, surge current rating 160 kA per phase", page_hint=1)
    assert moved.verified and moved.page == 2  # wrong page hint is corrected
    fake = make_evidence(d, "Short-circuit current rating 100 kA RMS with copper bus throughout")
    assert not fake.verified


def test_bm25_finds_relevant_passage():
    from keystone.docs import BM25, passages, store

    d = store().ingest_path(ALPHA / "submittal_voltara_swg1.pdf", "submittal")
    ps = passages(d)
    top = BM25([p.text for p in ps]).top("surge protective device kA per phase", k=1)[0]
    assert "SPD" in ps[top].text or "Surge" in ps[top].text


# --------------------------------------------------------------------------------- lead time


def test_lead_time_forecast_is_a_range_with_sources():
    from keystone.agents.leadtime import predict_lead_times

    r = predict_lead_times(
        [
            {"item_id": "X1", "description": "480V switchgear lineup 4000A", "quoted_lead_weeks": 30, "order_date": "2026-12-01", "need_by_date": "2027-09-01", "shipment_mode": "Ocean"},
            {"item_id": "X2", "description": "Gold-plated widget", "order_date": "2026-12-01"},
        ],
        use_llm=False,
    )
    f1, f2 = r.result["forecasts"]
    lt = f1["forecast"]["lead_time_weeks"]
    assert lt["p10"] <= lt["p50"] <= lt["p90"] and lt["p90"] > 30
    assert f1["evidence"] and all(e["url"].startswith("https://") for e in f1["evidence"])
    assert 0 <= f1["forecast"]["p_on_time_vs_need_by"] <= 1
    assert f1["supplier_promise"]["position_vs_market"].startswith("below")  # 30 wks < market P10 -> sceptical
    assert f2["forecast"] is None and f2["needs_human"]  # unknown item: refuses to guess
    assert r.human_review.required


# ---------------------------------------------------------------------------------- schedule


def test_schedule_cpm_and_monte_carlo():
    from keystone.agents.schedule import assess_schedule_risk

    r = assess_schedule_risk((ALPHA / "schedule.csv").read_text(), (ALPHA / "purchase_orders.csv").read_text(), "2026-12-01", "2028-01-31", use_llm=False)
    assert r.status in ("complete", "needs_human_review"), r.summary
    cpm = {a["activity_id"]: a for a in r.result["cpm"]}
    assert cpm["A100"]["early_start"] == "2026-12-01"
    assert cpm["A220"]["early_finish"] == r.result["simulation"]["planned_finish_without_material_risk"]
    risks = r.result["risks"]
    assert [x["rank"] for x in risks] == list(range(1, len(risks) + 1))
    assert risks[0]["expected_project_delay_caused_days"] >= risks[-1]["expected_project_delay_caused_days"]
    assert 0 <= r.result["simulation"]["p_meet_target"] <= 1
    assert all(x["evidence"] for x in risks)


def test_schedule_rejects_cycles():
    from keystone.agents.schedule import assess_schedule_risk

    sched = "activity_id,name,duration_days,predecessors,requires_po\nA,a,1,B,\nB,b,1,A,\n"
    po = "po_number,item,vendor,order_date,quoted_lead_weeks,promised_date,shipment_mode,status\n"
    r = assess_schedule_risk(sched, po, "2026-01-01", use_llm=False)
    assert r.status == "error" and "cycle" in r.summary


# --------------------------------------------------------------------------------- grounding


def test_grounding_guard_rejects_invented_numbers():
    from keystone.grounding import unsupported_numbers

    facts = {"total": 1068250.0, "margin_pct": 1.8, "bidder": "Voltara"}
    assert unsupported_numbers("Voltara at $1,068,250, 1.8% below the next bid.", facts) == []
    assert unsupported_numbers("Voltara at $1.07M (about 1.8%).", facts) == []
    assert unsupported_numbers("Voltara saves $250,000 versus Helix.", facts) == ["250,000"]


# ------------------------------------------------------------------------- agents w/ mocked LLM


def test_compliance_pipeline_with_mocked_llm(monkeypatch):
    from keystone.agents import compliance
    from keystone.docs import store

    spec = store().ingest_path(ALPHA / "spec_26_23_00_lv_switchgear.pdf", "spec")
    sub = store().ingest_path(ALPHA / "submittal_voltara_swg1.pdf", "submittal")

    def fake(system, user, **kw):
        if "extract every atomic" in system:
            return {"requirements": [
                {"ref": "2.2.C", "title": "SCCR", "requirement": "SCCR >= 65 kA", "quote": "Short-circuit current rating shall be not less than 65 kA RMS symmetrical at 480 V", "page": 1, "parameter": "SCCR", "comparator": ">=", "value": 65, "unit": "kA", "criticality": "critical"},
                {"ref": "2.3.E", "title": "Lineup length", "requirement": "<= 240 in", "quote": "The overall lineup length shall not exceed 240 inches", "page": 1, "parameter": "length", "comparator": "<=", "value": 240, "unit": "in", "criticality": "critical"},
                {"ref": "2.7.A", "title": "Seismic", "requirement": "seismic cert", "quote": "Switchgear shall be seismically qualified per IBC 2021", "page": 2, "parameter": "seismic", "comparator": "text", "value": None, "unit": None, "criticality": "critical"},
            ]}
        if "meticulous submittal reviewer" in system:
            return {"findings": [
                {"ref": "2.2.C", "verdict": "deviate", "submittal_quote": "50 kA RMS symmetrical at 480 V (fully rated)", "page": 1, "offered_value": 50, "offered_unit": "kA", "certainty": 0.9},
                # model wrongly says comply; the rule check (6400 mm = 252 in > 240 in) must override and flag it
                {"ref": "2.3.E", "verdict": "comply", "submittal_quote": "Overall lineup length: 6,400 mm", "page": 1, "offered_value": 6400, "offered_unit": "mm", "certainty": 0.8},
                {"ref": "2.7.A", "verdict": "missing", "submittal_quote": "", "page": None, "certainty": 0.8},
            ]}
        if "independent second reviewer" in system:
            return {"checks": [{"ref": "2.2.C", "verdict": "deviate", "note": "50<65"}, {"ref": "2.3.E", "verdict": "deviate", "note": "252 in"}, {"ref": "2.7.A", "verdict": "missing", "note": ""}], "_served_by": "verifier-x"}
        raise AssertionError(system[:60])

    monkeypatch.setattr(compliance, "chat_json", fake)
    r = compliance.check_compliance(spec.doc_id, sub.doc_id)
    f = {x["ref"]: x for x in r.result["findings"]}
    assert f["2.2.C"]["verdict"] == "deviate" and f["2.2.C"]["evidence"]["submittal"]["verified"]
    assert f["2.3.E"]["verdict"] == "deviate" and f["2.3.E"]["model_verdict"] == "comply"
    assert f["2.3.E"]["needs_human"] and f["2.3.E"]["confidence"]["score"] <= 0.55
    assert f["2.7.A"]["verdict"] == "missing"
    assert f["2.2.C"]["verifier"]["model"] == "verifier-x"
    assert r.result["recommended_action"] == "Revise and Resubmit"
    assert r.result["review_comments"]["requires_approval_to_send"]
    assert r.status == "needs_human_review"


def test_bid_leveling_math_with_mocked_llm(monkeypatch):
    from keystone.agents import bids
    from keystone.docs import store

    a = store().ingest_text("Bid A\nLineup $100\nFreight $10\nTOTAL $110", "a.txt", "bid")
    b = store().ingest_text("Bid B\nLineup $90\nTOTAL $95\nFreight excluded", "b.txt", "bid")
    scope = ["Lineup", "Freight"]

    def fake(system, user, **kw):
        if "leveling subcontractor/vendor bids" in system:
            if "Bid A" in user:
                return {"bidder": "A", "stated_total": 110, "line_items": [{"description": "Lineup", "price": 100, "quote": "Lineup $100"}, {"description": "Freight", "price": 10, "quote": "Freight $10"}],
                        "scope": [{"item": "Lineup", "status": "included", "price": 100, "quote": "Lineup $100"}, {"item": "Freight", "status": "included", "price": 10, "quote": "Freight $10"}]}
            return {"bidder": "B", "stated_total": 95, "line_items": [{"description": "Lineup", "price": 90, "quote": "Lineup $90"}],
                    "exclusions": [{"text": "Freight excluded", "quote": "Freight excluded"}],
                    "scope": [{"item": "Lineup", "status": "included", "price": 90, "quote": "Lineup $90"}, {"item": "Freight", "status": "excluded", "price": None, "quote": "Freight excluded"}]}
        return {"memo": "Recommend B."}

    monkeypatch.setattr(bids, "chat_json", fake)
    import keystone.grounding as g

    monkeypatch.setattr(g, "chat_json", fake)
    r = bids.level_bids([a.doc_id, b.doc_id], scope)
    by = {x["bidder"]: x for x in r.result["bids"]}
    assert by["B"]["arithmetic_error"]["sum_of_line_items"] == 90  # stated 95 but items sum to 90
    assert by["B"]["leveling"]["plugs"][0]["amount"] == 10  # freight plugged at A's price
    assert by["B"]["leveling"]["leveled_total"] == 100
    assert r.result["recommendation"]["bidder"] == "B"
    assert r.result["citation_verification_rate"] == 1.0


def test_shared_envelope_is_serialisable():
    from keystone.agents.leadtime import predict_lead_times

    r = predict_lead_times([{"item_id": "T", "description": "2500 kVA pad-mounted transformer", "order_date": "2026-12-01"}], use_llm=False)
    d = json.loads(r.model_dump_json())
    for k in ("schema_version", "agent", "run_id", "status", "summary", "result", "confidence", "human_review", "usage"):
        assert k in d
