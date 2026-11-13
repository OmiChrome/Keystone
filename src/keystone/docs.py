"""Document ingestion, page-addressable storage, quote verification and lexical retrieval.

Anti-hallucination core: every quote an LLM attributes to a document is located in the real page
text (exact match first, then fuzzy alignment). Quotes that cannot be found are marked
``verified=False`` and drag the finding's confidence down, so invented citations never pass as facts.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from rapidfuzz import fuzz

from .config import settings
from .schemas import Evidence


@dataclass
class Document:
    doc_id: str
    name: str
    pages: list[str]
    kind: str = "document"  # spec | submittal | bid | schedule | po | document
    source_path: str | None = None
    meta: dict = field(default_factory=dict)

    @property
    def n_pages(self) -> int:
        return len(self.pages)

    def numbered_text(self, max_chars: int | None = None) -> str:
        out, total = [], 0
        for i, p in enumerate(self.pages, 1):
            block = f"<<PAGE {i}>>\n{p.strip()}\n"
            if max_chars and total + len(block) > max_chars:
                out.append(f"<<TRUNCATED after page {i - 1}>>")
                break
            out.append(block)
            total += len(block)
        return "\n".join(out)

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "name": self.name,
            "kind": self.kind,
            "n_pages": self.n_pages,
            "source_path": self.source_path,
            "meta": self.meta,
        }


def _doc_id(name: str, pages: list[str]) -> str:
    h = hashlib.sha256(("\f".join(pages)).encode()).hexdigest()[:10]
    stem = re.sub(r"[^a-z0-9]+", "-", Path(name).stem.lower()).strip("-")[:40]
    return f"{stem}-{h}"


def extract_pages(path: Path) -> list[str]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        import pdfplumber

        pages = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                txt = page.extract_text(layout=False) or ""
                pages.append(txt)
        return pages
    text = path.read_text(errors="replace")
    if suffix == ".csv":
        return [text]
    return [p for p in text.split("\f")] or [text]


class DocStore:
    """Process-wide registry of ingested documents (persisted to runs/docs for restarts)."""

    def __init__(self, root: Path | None = None):
        self.root = (root or settings.runs_dir) / "docs"
        self.docs: dict[str, Document] = {}
        self.lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not self.root.exists():
            return
        for f in self.root.glob("*.json"):
            try:
                d = json.loads(f.read_text())
                self.docs[d["doc_id"]] = Document(**d)
            except Exception:
                continue

    def add(self, doc: Document) -> Document:
        with self.lock:
            self.docs[doc.doc_id] = doc
            try:
                self.root.mkdir(parents=True, exist_ok=True)
                (self.root / f"{doc.doc_id}.json").write_text(json.dumps(doc.__dict__))
            except OSError:
                pass
        return doc

    def ingest_path(self, path: str | Path, kind: str = "document", name: str | None = None) -> Document:
        path = Path(path)
        pages = extract_pages(path)
        name = name or path.name
        return self.add(Document(_doc_id(name, pages), name, pages, kind, str(path)))

    def ingest_text(self, text: str, name: str, kind: str = "document") -> Document:
        pages = text.split("\f")
        return self.add(Document(_doc_id(name, pages), name, pages, kind))

    def get(self, doc_id: str) -> Document:
        if doc_id not in self.docs:
            self._ingest_samples()  # serverless cold start: sample doc ids are deterministic, rebuild them
        if doc_id not in self.docs:
            raise KeyError(f"unknown doc_id {doc_id!r}; ingest it first")
        return self.docs[doc_id]

    def _ingest_samples(self) -> None:
        from .config import ROOT

        for p in sorted((ROOT / "samples").glob("*/*.pdf")):
            kind = p.name.split("_")[0] if p.name.split("_")[0] in ("spec", "submittal", "bid") else "document"
            try:
                self.ingest_path(p, kind)
            except Exception:
                continue

    def list(self) -> list[dict]:
        return [d.to_dict() for d in self.docs.values()]


_store: DocStore | None = None


def store() -> DocStore:
    global _store
    if _store is None:
        _store = DocStore()
    return _store


# ------------------------------------------------------------------------------ quote verification


def _norm(s: str) -> str:
    s = s.lower().replace("–", "-").replace("—", "-").replace("’", "'")
    s = s.replace("“", '"').replace("”", '"').replace(" ", " ")
    s = re.sub(r"-\s*\n\s*", "", s)  # hyphenated line breaks
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def locate_quote(doc: Document, quote: str, page_hint: int | None = None) -> tuple[int | None, float]:
    """Return (1-based page, score 0-100) of the best location of ``quote`` in ``doc``."""
    q = _norm(quote)
    if len(q) < 3:
        return (None, 0.0)
    order = list(range(len(doc.pages)))
    if page_hint and 1 <= page_hint <= len(doc.pages):
        order.remove(page_hint - 1)
        order.insert(0, page_hint - 1)
    best_page, best = None, 0.0
    for i in order:
        p = _norm(doc.pages[i])
        if q in p:
            return (i + 1, 100.0)
        if len(q) > len(p) + 20:
            continue
        sc = fuzz.partial_ratio(q, p)
        if sc > best:
            best_page, best = i + 1, sc
    return (best_page, round(best, 1))


VERIFY_THRESHOLD = 90.0


def make_evidence(doc: Document, quote: str, page_hint: int | None = None, locator: str | None = None) -> Evidence:
    page, score = locate_quote(doc, quote or "", page_hint)
    return Evidence(
        doc_id=doc.doc_id,
        doc_name=doc.name,
        page=page if page else page_hint,
        locator=locator,
        quote=(quote or "").strip(),
        verified=score >= VERIFY_THRESHOLD,
        match_score=score,
    )


# ------------------------------------------------------------------------------------------- BM25

_TOK = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")


def tokenize(s: str) -> list[str]:
    return _TOK.findall(s.lower())


@dataclass
class Passage:
    doc_id: str
    page: int
    text: str


def passages(doc: Document, window: int = 6, stride: int = 3) -> list[Passage]:
    out = []
    for pi, page in enumerate(doc.pages, 1):
        lines = [ln for ln in page.splitlines() if ln.strip()]
        if not lines:
            continue
        for s in range(0, max(1, len(lines) - window + stride), stride):
            out.append(Passage(doc.doc_id, pi, "\n".join(lines[s : s + window])))
    return out


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.4, b: float = 0.75):
        self.toks = [tokenize(d) for d in docs]
        self.k1, self.b = k1, b
        self.avg = sum(map(len, self.toks)) / max(1, len(self.toks))
        df = Counter(t for d in self.toks for t in set(d))
        n = len(self.toks)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.tf = [Counter(d) for d in self.toks]

    def scores(self, query: str) -> list[float]:
        q = tokenize(query)
        out = []
        for tf, toks in zip(self.tf, self.toks):
            s = 0.0
            for t in q:
                if t in tf:
                    f = tf[t]
                    s += self.idf.get(t, 0) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * len(toks) / self.avg))
            out.append(s)
        return out

    def top(self, query: str, k: int = 5) -> list[int]:
        sc = self.scores(query)
        return sorted(range(len(sc)), key=lambda i: -sc[i])[:k]
