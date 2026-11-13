# Research notes — what exists, what wins, what we borrowed

Researched 2026-11-13. We borrowed ideas and product patterns, not code, branding or page designs.

## Commercial landscape (construction procurement AI)

| Product | What it does | Idea we adopted |
|---|---|---|
| Trunk Tools — TrunkSubmittal ([FAQ](https://intercom.help/trunk-tools/en/articles/12693264-trunksubmittal-submittal-review-faq)) | Flags missing / conflicting / non-compliant submittal details against specs. Plugs into Procore/Autodesk as a reviewer step and drafts emails to the trade. | **Draft vendor email** built only from verified findings, held for approval before sending (`review_comments.draft_email`) |
| Datagrid, a Procore company ([spec compliance agent](https://datagrid.com/agents/for/automate-spec-compliance-checking), [bid leveling](https://datagrid.com/agents/for/bid-leveling-sheet)) | Spec-vs-submittal cross-check producing structured compliance documentation; scope checker between bid receipt and award | Structured output per requirement; humans keep award authority (the pipeline **always** asks for sign-off) |
| Nomic ([AI bid leveling](https://www.nomic.ai/glossary/ai-bid-leveling)) | Normalises bids to a common framework, maps inclusions and exclusions, flags prices that look low or high | **Common-scope matrix + plug pricing at the median of other bidders** |
| Zebel AI Bid Review ([press](https://www.constructiondive.com/press-release/20261016-zebel-launches-ai-bid-review-cutting-a-week-of-manual-bid-entry-out-of-eve-1/)) | Reads incoming sub bids and checks each one; the CEO's line: "handing the whole thing to an AI and hoping is not the answer" | Confidence-gated **human hand-off** |
| InspectMind, BuildSync, Redline Build | Submittal checkers | — |

Gap we target: these products publish vendor-reported speed numbers, and we found **no published accuracy benchmarks**. They are
closed and built as SaaS UIs, not as callable sub-agents. Keystone instead:

- ships **ground truth and an eval harness** with a **held-out set**,
- exposes every specialist over **MCP**,
- **verifies every quote**.

## Open source

- `rafaeltuelho/construction-spec-assistant`: a LangChain notebook for spec-vs-submittal inconsistencies (about 9 stars).
- "CheckMate": FastAPI and LangGraph, spec requirements against a submittal package (a portfolio project, no repository found).

## Winning hackathon projects: what made them win

- **AuditChain, START Hack 2026 winner, procurement challenge** ([write-up](https://landigf.github.io/starthack-2026-auditchain.html)).
  Its core rule: *"the LLM can parse and explain, but it does not decide"*. It used a deterministic policy engine, confidence gating
  (approve / escalate / reject), a persisted audit trail that could be replayed, and visible observability.
  → We apply the same principle: rule checks, leveling, CPM and Monte Carlo are code, and the LLM writes narratives only after the facts are fixed.
  We added an audit log with a per-call trace and a "How this was decided" panel for each finding.
- **VendorGuard, Microsoft Agent Academy 2026, top score**: a multi-agent vendor-contract compliance system.
- **Judging advice** ([dev.to](https://dev.to/kurbaitaev/what-judges-actually-score-notes-from-a-year-of-hackathon-judging-3p4l),
  [AngelHack](https://angelhack.com/blog/ai-agent-hackathon/)):
  - A live demo that works end to end.
  - A one-line identity.
  - A specific user.
  - Being honest about limits.
  - Not depending on venue Wi-Fi.
  - Measuring hallucination rate.

  → What we did:
  - Every demo response is **cached on disk**, so the demo replays offline.
  - The README has a **Known limitations** section.
  - We **report citation verification as our hallucination metric**.
  - The held-out miss stays in the report.

## Lead-time data sources

See `src/keystone/data/leadtime_reference.json`; every range there links to the article it came from. Supplier
promise reliability comes from `scripts/build_promise_model.py`, built on the USAID SCMS public delivery history.
