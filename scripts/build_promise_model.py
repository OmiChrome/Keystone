"""Build Keystone's *supplier promise reliability* model from real, public delivery data.

Source: USAID Supply Chain Management System (SCMS) "Supply Chain Shipment Pricing Data" - 10,324
line items, 2006-2015, with PO-sent, scheduled-delivery and delivered-to-client dates. The original
portal (data.usaid.gov, view a3rc-nmf6) no longer resolves; we read the public mirror below and verify
its SHA-256 against the hash recorded for the original release. Attribution: USAID Development Data
Library. Only derived aggregates are committed (the raw CSV may be CC BY-ND 4.0).

What we learn: how far real deliveries slip past the date the supplier promised, as a ratio of the
promised lead time, by shipment mode. Keystone's lead-time agent applies this empirical slip
distribution on top of a vendor's quoted lead time. We also run a chronological calibration test (fit <= 2012,
test >= 2013) and record how often real deliveries arrived by each predicted quantile, so the honesty of
our ranges is measured rather than assumed.

Usage:  uv run python scripts/build_promise_model.py
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import httpx
import numpy as np

URL = "https://raw.githubusercontent.com/jrcinco/supply-chain-shipment-price-data/master/SCMS_Delivery_History_Dataset.csv"
SHA256 = "918b992dd3e8d4b64d2a727b2c4ea607603d0c58f19484e73f7b78528c6a8673"
OUT = Path(__file__).resolve().parents[1] / "src" / "keystone" / "data" / "promise_reliability.json"
CACHE = Path(__file__).resolve().parents[1] / ".cache" / "SCMS_Delivery_History_Dataset.csv"


def load() -> bytes:
    if CACHE.exists():
        raw = CACHE.read_bytes()
    else:
        raw = httpx.get(URL, follow_redirects=True, timeout=120).content
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_bytes(raw)
    got = hashlib.sha256(raw).hexdigest()
    if got != SHA256:
        raise SystemExit(f"SHA-256 mismatch: {got} != {SHA256}")
    return raw


def main() -> None:
    import csv
    from datetime import datetime

    raw = load()
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig", errors="replace"), newline="")))

    def d(s: str):
        for fmt in ("%d-%b-%y", "%m/%d/%y", "%Y-%m-%d"):
            try:
                return datetime.strptime(s.strip(), fmt)
            except ValueError:
                pass
        return None

    recs = []
    for r in rows:
        po, sch, dlv = d(r["PO Sent to Vendor Date"]), d(r["Scheduled Delivery Date"]), d(r["Delivered to Client Date"])
        if not (po and sch and dlv):
            continue
        planned = (sch - po).days
        actual = (dlv - po).days
        if planned < 14 or actual <= 0:
            continue
        recs.append({"mode": (r["Shipment Mode"] or "Unknown").strip(), "planned": planned, "actual": actual, "year": po.year})

    ratio = np.array([r["actual"] / r["planned"] for r in recs])
    modes = sorted({r["mode"] for r in recs})

    def profile(mask) -> dict:
        x = ratio[mask]
        late = x[x > 1.0]
        qs = np.linspace(0.01, 0.99, 99)
        return {
            "n": int(mask.sum()),
            "p_late": round(float((x > 1.0).mean()), 4),
            "p_late_over_10pct": round(float((x > 1.10).mean()), 4),
            "slip_ratio_quantiles_given_late": {f"p{int(q*100)}": round(float(np.quantile(late, q)), 4) for q in (0.5, 0.75, 0.9, 0.95)} if len(late) else {},
            "late_slip_ratio_samples": [round(float(v), 4) for v in np.quantile(late, qs)] if len(late) >= 10 else [],
        }

    by_mode = {m: profile(np.array([r["mode"] == m for r in recs])) for m in modes}
    overall = profile(np.ones(len(recs), dtype=bool))

    # ---- calibration test (chronological, one-sided quantiles = "arrives by" dates) ---------------
    # Fit the slip distribution on <= 2012, test on >= 2013: how often did real deliveries arrive by
    # the model's P50/P80/P90/P95 date? Well-calibrated => realised ~= nominal.
    years = np.array([r["year"] for r in recs])
    tr, te = years <= 2012, years >= 2013
    calib = {}
    for q in (0.5, 0.8, 0.9, 0.95):
        thr = float(np.quantile(ratio[tr], q))
        calib[f"p{int(q*100)}"] = {"predicted_slip_ratio": round(thr, 4), "realised_share_on_or_before": round(float((ratio[te] <= thr + 1e-9).mean()), 4)}
    exceed = {
        "p_late_train": round(float((ratio[tr] > 1).mean()), 4),
        "p_late_test": round(float((ratio[te] > 1).mean()), 4),
    }

    out = {
        "_source": {
            "dataset": "USAID SCMS Supply Chain Shipment Pricing Data (delivery history 2006-2015)",
            "original": "https://data.usaid.gov/HIV-AIDS/Supply-Chain-Shipment-Pricing-Data/a3rc-nmf6 (no longer resolves)",
            "mirror": URL,
            "sha256": SHA256,
            "attribution": "USAID Development Data Library",
            "rows_used": len(recs),
            "filter": "PO, scheduled and delivered dates present; promised lead time >= 14 days",
            "caveat": "Health-commodity shipments, not construction equipment. Used only as an empirical prior on how far deliveries slip past a supplier's promised date; the construction reference classes set the lead-time level.",
        },
        "definition": "slip_ratio = actual lead time / promised lead time (PO sent -> delivered vs PO sent -> scheduled)",
        "overall": overall,
        "by_shipment_mode": by_mode,
        "calibration_test": {
            "split": "fit <= 2012, test >= 2013 (chronological)",
            "n_fit": int(tr.sum()), "n_test": int(te.sum()),
            "quantiles": calib,
            **exceed,
        },
    }
    OUT.write_text(json.dumps(out, indent=1))
    print(json.dumps(out["calibration_test"], indent=1)); print({m: (p["n"], p["p_late"]) for m, p in by_mode.items()})


if __name__ == "__main__":
    main()
