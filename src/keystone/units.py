"""Deterministic quantity handling: parse numbers+units, convert, and compare against a requirement.

This is the symbolic half of the neuro-symbolic compliance check: the LLM extracts *what* the spec
requires and *what* the submittal offers; Python decides whether the numbers actually satisfy the
requirement. When the two disagree, the finding is escalated to a human instead of being guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# unit alias -> (dimension, factor to canonical unit)
UNITS: dict[str, tuple[str, float]] = {
    # current
    "a": ("current", 1), "amp": ("current", 1), "amps": ("current", 1), "ampere": ("current", 1),
    "ka": ("current", 1000), "kaic": ("current", 1000), "ka rms": ("current", 1000), "ka sym": ("current", 1000),
    # voltage
    "v": ("voltage", 1), "vac": ("voltage", 1), "volt": ("voltage", 1), "volts": ("voltage", 1),
    "kv": ("voltage", 1000),
    # power
    "w": ("power", 1), "kw": ("power", 1e3), "mw": ("power", 1e6),
    "ton": ("power", 3516.85), "tons": ("power", 3516.85), "tr": ("power", 3516.85),
    "btu/h": ("power", 0.29307107), "btuh": ("power", 0.29307107), "mbh": ("power", 293.07107),
    # apparent power
    "va": ("apparent_power", 1), "kva": ("apparent_power", 1e3), "mva": ("apparent_power", 1e6),
    # length
    "mm": ("length", 0.001), "cm": ("length", 0.01), "m": ("length", 1), "in": ("length", 0.0254),
    "inch": ("length", 0.0254), "inches": ("length", 0.0254), '"': ("length", 0.0254),
    "ft": ("length", 0.3048), "feet": ("length", 0.3048), "'": ("length", 0.3048),
    # mass
    "kg": ("mass", 1), "lb": ("mass", 0.45359237), "lbs": ("mass", 0.45359237), "t": ("mass", 1000),
    # sound
    "db": ("sound", 1), "dba": ("sound", 1), "db(a)": ("sound", 1),
    # frequency
    "hz": ("frequency", 1),
    # ratio
    "%": ("percent", 1), "percent": ("percent", 1),
    # time
    "day": ("time", 1), "days": ("time", 1), "week": ("time", 7), "weeks": ("time", 7), "wk": ("time", 7),
    "wks": ("time", 7), "month": ("time", 30.44), "months": ("time", 30.44), "year": ("time", 365.25),
    "years": ("time", 365.25), "yr": ("time", 365.25), "yrs": ("time", 365.25),
    # efficiency
    "kw/ton": ("kw_per_ton", 1), "kw/tr": ("kw_per_ton", 1),
    # pressure
    "psi": ("pressure", 6894.76), "kpa": ("pressure", 1000), "pa": ("pressure", 1), "bar": ("pressure", 1e5),
    # temperature handled specially
    "°f": ("temp_f", 1), "f": ("temp_f", 1), "°c": ("temp_c", 1), "c": ("temp_c", 1),
}


def norm_unit(u: str | None) -> str | None:
    if u is None:
        return None
    u = u.strip().lower().replace("deg ", "°").replace("degrees ", "°")
    u = re.sub(r"\s+", " ", u)
    if u in UNITS:
        return u
    u2 = u.replace(" ", "")
    if u2 in UNITS:
        return u2
    # strip trailing qualifiers like "ka symmetrical", "v ac"
    head = u.split(" ")[0]
    return head if head in UNITS else None


def to_canonical(value: float, unit: str | None) -> tuple[str | None, float]:
    nu = norm_unit(unit)
    if nu is None:
        return (None, value)
    dim, f = UNITS[nu]
    if dim == "temp_f":
        return ("temperature", (value - 32) * 5 / 9)
    if dim == "temp_c":
        return ("temperature", value)
    return (dim, value * f)


@dataclass
class RuleCheck:
    status: str  # comply | deviate | unknown | n/a
    explanation: str


_NUM = re.compile(r"^-?\d[\d,]*\.?\d*$")


def _num(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    try:
        return float(s)
    except ValueError:
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        return float(m.group()) if m else None


TOL = 1e-6


def compare(requirement: dict, offered: dict) -> RuleCheck:
    """requirement: {comparator: '>=','<=','==','range','text', value, value_max?, unit}
    offered: {value, unit}"""
    comp = (requirement.get("comparator") or "text").strip()
    if comp in ("text", "", "none", None):
        return RuleCheck("n/a", "qualitative requirement - judged from text")
    rv, ru = _num(requirement.get("value")), requirement.get("unit")
    ov, ou = _num(offered.get("value")) if offered else None, (offered or {}).get("unit")
    if rv is None:
        return RuleCheck("n/a", "requirement has no numeric value")
    if ov is None:
        return RuleCheck("unknown", "no numeric value offered in submittal")
    rd, rc = to_canonical(rv, ru)
    od, oc = to_canonical(ov, ou)
    if rd != od:
        if rd is None and od is None:
            rc, oc = rv, ov
        else:
            return RuleCheck("unknown", f"incompatible units: required '{ru}' vs offered '{ou}'")
    unit_note = "" if (norm_unit(ru) == norm_unit(ou)) else f" (converted {ov:g} {ou} -> {oc / (rc / rv) if rv else oc:.4g} {ru})"
    if comp == ">=":
        ok = oc >= rc - abs(rc) * TOL
        return RuleCheck("comply" if ok else "deviate", f"offered {ov:g} {ou or ''} {'>=' if ok else '<'} required {rv:g} {ru or ''}{unit_note}")
    if comp == "<=":
        ok = oc <= rc + abs(rc) * TOL
        return RuleCheck("comply" if ok else "deviate", f"offered {ov:g} {ou or ''} {'<=' if ok else '>'} limit {rv:g} {ru or ''}{unit_note}")
    if comp == "==":
        ok = abs(oc - rc) <= max(abs(rc) * 0.005, TOL)
        return RuleCheck("comply" if ok else "deviate", f"offered {ov:g} {ou or ''} {'=' if ok else '!='} required {rv:g} {ru or ''}{unit_note}")
    if comp == "range":
        vmax = _num(requirement.get("value_max"))
        if vmax is None:
            return RuleCheck("unknown", "range requirement without upper bound")
        _, rmax = to_canonical(vmax, ru)
        ok = rc - abs(rc) * TOL <= oc <= rmax + abs(rmax) * TOL
        return RuleCheck("comply" if ok else "deviate", f"offered {ov:g} {ou or ''} {'within' if ok else 'outside'} {rv:g}-{vmax:g} {ru or ''}{unit_note}")
    return RuleCheck("n/a", f"unsupported comparator {comp!r}")
