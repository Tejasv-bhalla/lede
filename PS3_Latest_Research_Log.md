# PS-3 — Living Research & Decision Log

**Case study:** AI Solutions Analyst (Zamp) — PS-3: Personalized Outreach, Prospect → Draft  
**Created/last updated:** 12 November 2026  
**State:** Pre-build research + initial technical feasibility spike (not a completed system)  
**Time constraint:** User reports ~48 hours available from 11 Nov; prioritize a running demo, not broad research.

> **Truth labels used here:** `DOCUMENT REQUIREMENT` = explicitly in candidate guide; `PUBLICLY CHECKED` = corroborated against a public source; `PROPOSED` = project decision/hypothesis; `TESTED OFFLINE` = a locally executed fixture test; `NOT TESTED` = still uncertain.

## 1) What Zamp actually requires

**Source:** User-supplied *ASA Case Study — Candidate Guide (2026)*, pages 1–7.

- `DOCUMENT REQUIREMENT` Select **one** problem statement; for PS-3, input a prospect, research relevant real signals, identify the strongest hook, and produce a **personalized outreach draft**. Keep a **human reviewer before sending**. (Page 5)
- `DOCUMENT REQUIREMENT` Build **2–4 realistic edge cases** chosen by us. (Page 5)
- `DOCUMENT REQUIREMENT` Deliver a **live, runnable process**, not a mock-up, that accepts actual input, executes stages, and generates actual output. (Pages 1–2)
- `DOCUMENT REQUIREMENT` Provide a **live execution view** and ability to inspect run histories/statuses/outputs. Page 2 stresses an intuitive UI; page 7 clarifies a simple dashboard, structured log, or clean console can be sufficient. (Pages 2, 7)
- `DOCUMENT REQUIREMENT` Submit the **runnable process link** and **5-minute maximum video** showing a happy path plus at least one edge case. If advanced, demonstrate live without slides. (Pages 1–2)
- `DOCUMENT REQUIREMENT` Tool selection is open; real public company research or plausible fictional test inputs are allowed. Do not use Zamp or Pace for the build. (Page 7)
- `DOCUMENT REQUIREMENT` Document assumptions, implement the happy path first, and prioritize working end-to-end behavior. (Pages 6–7)

## 2) Problem and target context

**Business problem:** SDRs cannot economically perform deep manual research across large prospect lists. Generic mass-personalization underperforms the intent of thoughtful outreach. The automation should transform a named target into a human-reviewable, evidence-backed email draft.

**Prototype sales offer — `PROPOSED`, NOT LOCKED:** AI Support Triage Copilot for B2B SaaS teams, supporting classification, retrieval of documentation, and routing to human specialists. This hypothetical product needs clear guardrails: avoid unsubstantiated product feature claims, guarantees, and quantitative ROI statements.

**Buyer persona — `PROPOSED`:** Head of Customer Support, Customer Experience, or Support Operations at a B2B SaaS firm. The app will accept `name (optional)`, `company`, `company_domain`, `role`, and a seller-side `product_name`/`product_value_proposition`.

**User job-to-be-done:** "Find a specific, supportable reason to approach this prospect and produce a credible first draft I can inspect, edit, and choose to send myself."

**Out of scope for 48-hour MVP:** automatic sending, CRM integrations, mass prospecting, LinkedIn scraping, contact enrichment, multi-agent complexity, full-site crawling, elaborate analytics.

## 3) Source and competitor research

### Current tools/technology

| Resource | Supported / observed capability | Our implication | Confidence |
|---|---|---|---|
| Tavily Python SDK | Search and Extract APIs; current SDK README describes **keyless rate-limited** use for search/extract, or API-key use. | Candidate for rapid targeted retrieval; test keyless access and response quality first. | PUBLICLY CHECKED documentation, not live-benchmarked |
| Tavily Search API | Accepts queries, `max_results`, `include_raw_content`; gives URLs and page content/snippets. | Retrieve up to ~5 sources per focused query. | PUBLICLY CHECKED documentation |
| Streamlit `st.status` | Execution-status container with running/complete/error states. | Build an inspectable run view quickly. | PUBLICLY CHECKED documentation |

References:
- Tavily Python SDK README: https://github.com/tavily-ai/tavily-python
- Tavily Search API documentation: https://help.tavily.com/articles/4840311948-tavily-search-api
- Tavily API reference: https://github.com/tavily-ai/tavily-power/blob/main/steering/api-reference.md
- Streamlit status documentation: https://docs.streamlit.io/develop/api-reference/status/st.status

**Warnings:** Search results can be stale or incomplete, pages can change, timestamps may not exist, API pricing/limits can change, and a source that contains relevant words is not automatically credible or relevant. Keyless mode availability in documentation is not proof it works in our deployment environment.

### Prospect research example — Supabase

`PUBLICLY CHECKED` On 12 Nov 2026, the official Supabase careers page listed multiple support-related positions and a Billing Support Specialist role.

- Careers: https://supabase.com/careers
- Billing Support Specialist: https://jobs.ashbyhq.com/supabase/8999613e-cbca-4a00-9516-09681a46749e

The Billing Support Specialist listing says the person would **triage support cases, direct users to previous answers/documentation, escalate to appropriate specialists, and identify internal tooling opportunities**. This is a direct observation from the listed responsibilities.

**Reasoned interpretation (`PROPOSED`):** Support triage and workflow efficiency might be a suitable outreach topic for our hypothetical product.

**Explicitly not established:** that Supabase has poor support, is overwhelmed, currently needs our software, that the job was *recently posted*, or that any specific named leader is responsible. We must not put such claims in drafts without verification.

## 4) Recommended research workflow (`PROPOSED`)

```text
Seller/product context + prospect and company
    ↓
Validate target identity (company domain, person-role association)
    ↓
Generate 2–3 targeted research queries
    ↓
Retrieve results (Tavily or alternative)
    ↓
Collect content, URLs, source/published dates (if known), retrieval time
    ↓
Extract candidate factual statements + exact supporting passages
    ↓
Hard evidence gates: target match, claim support, temporal validity
    ↓
Rank eligible signals for sales relevance (LLM judgment with explanation)
    ↓
If no valid signal -> Insufficient Evidence / Needs Review
    ↓
Generate short email draft using ONLY accepted evidence
    ↓
Display evidence, ranking reasons, editable draft, human review
    ↓
Save execution events, status, result, errors, timestamps
```

**Decision:** Favor **targeted search**, not a general site crawler, for the initial demo. Bias queries toward relevant signals such as support hiring and operations-related announcements, then prioritize authoritative company-controlled sources.

**Important distinction:** A source's publication or event date and our retrieval time are DIFFERENT. A retrieved page is not automatically a new event.

## 5) Suggested data contracts (`PROPOSED`)

Input:

```json
{
  "prospect_name": "Optional, must be disambiguated if used",
  "company_name": "Supabase",
  "company_domain": "supabase.com",
  "prospect_role": "Head of Customer Support",
  "seller_product": "AI Support Triage Copilot",
  "seller_value": "Help teams triage routine issues and surface relevant docs"
}
```

Evidence record:

```json
{
  "signal_id": "s1",
  "company": "Supabase",
  "fact": "A job description mentions triaging support cases and improving support efficiency",
  "evidence_quote": "Exact substring or passage from retrieved page text",
  "source_title": "Billing Support Specialist",
  "source_url": "https://jobs.ashbyhq.com/supabase/8999613e-cbca-4a00-9516-09681a46749e",
  "published_at": null,
  "event_date": null,
  "retrieved_at": "2026-11-12T00:00:00Z",
  "company_match_verified": true,
  "eligibility": "eligible",
  "caveat": "Unknown publication date; do not call the posting new or recent",
  "business_relevance": "Directly mentions triage and support tooling"
}
```

Run record:

```json
{
  "run_id": "uuid",
  "state": "draft_ready | needs_review | insufficient_evidence | failed",
  "stages": ["input", "research", "extract", "validate", "rank", "draft"],
  "evidence": [],
  "selected_signal_id": "s1",
  "draft": {"subject": "...", "body": "...", "needs_human_review": true},
  "errors": [],
  "started_at": "ISO 8601 timestamp",
  "finished_at": "ISO 8601 timestamp"
}
```

### Rules vs. AI

- **Deterministic:** required fields; acceptable URL formatting; evidence passage present in stored text; actual source-date or expiry checks; unknown dates block claims such as "just announced"; never send automatically.
- **LLM assisted:** candidate fact extraction; business relevance and buyer-persona fit; concise email drafting.
- **Not solved by simple substring logic:** whether a claim accurately paraphrases source content, whether a source genuinely refers to the correct person, whether a page is authoritative, and whether an inference overstates the evidence. These need additional validation and/or human review.

**Priority policy:** A hard fail on evidence eligibility overrides a high relevance score. If a date is unknown, allow timeless phrasing about documented responsibilities but prohibit recency wording.

## 6) The test matrix

| Test | Setup | Expected action | Test state |
|---|---|---|---|
| Happy path: support-relevant evidence | Official Supabase role description | Eligible for research-signal consideration, no unverified recency claim | `TESTED OFFLINE` (stored fixture only) |
| Stale source | Synthetic application deadline before 12 Nov 2026 | Reject as a **current-hiring** claim | `TESTED OFFLINE` |
| Identity ambiguity | Synthetic same-name person, company not verified | Block prospect-specific claim | `TESTED OFFLINE` |
| Unsupported factual claim | Synthetic quote absent from stored source text | Reject claim | `TESTED OFFLINE` |
| Missing publication date | Synthetic signal described as "recent" but no date | Reject recency assertion | `TESTED OFFLINE` |
| Tavily retrieval | 3 real queries; source completeness and cost | Record source count, response time, and extractability | `NOT TESTED` |
| LLM claim extraction | Evaluate returned facts vs exact supporting passages | No unsupported outreach facts | `NOT TESTED` |
| End-to-end interactive demo | Input→search→verify→rank→draft→review and history | Runs without fixtures/hardcoded outcome | `NOT TESTED` |

## 7) Technical spike executed on 12 Nov 2026

**Artifact:** `PS3_feasibility_spike.py` in same directory.

**Executed:** `python PS3_feasibility_spike.py --mode fixtures`.

**Observed result:** 5/5 local checks passed. These tests used **curated fixtures**, not a live Tavily API request. They demonstrate only elementary eligibility gates: an evidence passage is stored, target has been pre-marked as matched, and date-sensitive cases are blocked when expired/undated.

**What they do NOT prove:** AI factual accuracy, identity matching, working retrieval, reliable extraction, relevance ranking quality, API latency, deployed runtime behavior, actual email drafting quality, or end-to-end product success.


### Environment check: live API reachability

`TESTED OFFLINE` On 12 Nov 2026, this assistant environment could not resolve `api.tavily.com` or `pypi.org` (DNS error: temporary failure in name resolution). Therefore **no Tavily HTTP request was executed**, no real Tavily response times were measured, and the API's keyless mode was not tested here. The live-mode command in the spike script is provided to run in a network-enabled local or hosted environment. This is an environment restriction, **not** evidence that Tavily is down.

### Optional live retrieval test

```bash
pip install tavily-python
python PS3_feasibility_spike.py --mode live --company Supabase
# Optional: export TAVILY_API_KEY='your_key'
```

This performs three search queries and saves result URLs/snippets and elapsed seconds in `PS3_spike_live_search_results.json`. Without a key it attempts Tavily's SDK-documented rate-limited keyless mode. It needs internet access. Do not interpret retrieval success as verified accuracy. Do not commit API keys.

**Live test acceptance gate:** at least two credible and company-matched sources, at least one nontrivial outreach-relevant signal, source URLs and stored supporting text, observed latency appropriate for a live demo, no bogus recency assertions.

## 8) Fast MVP architecture and implementation order (`PROPOSED`)

**Stack:** Python orchestration + Tavily retrieval + one structured-output LLM + Streamlit UI + durable run storage (SQLite for local development; persisted external storage if needed for cloud deployment).

**Order:**
1. Live Tavily smoke test; inspect actual result shape, noise, and latency. If blocked, switch to another permitted web-search provider rather than fake an API run.
2. Single end-to-end happy path using real research input, deterministic evidence store, and draft generation.
3. Show sources alongside claims; separate `not verified` from `verified` and `recent` from `date unknown`.
4. Add execution events and history.
5. Implement the three required edge cases: stale/expired, identity ambiguity, insufficient evidence. Use **real** edge-case behavior, not UI-only demonstrations.
6. Rehearse live runs; record <=5-minute video; verify public demo link and secrets handling.

### UI must-haves

- Input form with company, name/role (optional), and offer details.
- Explicit stage statuses and errors visible during a run.
- Evidence table: signal, source URL, publish/event date (if available), eligibility/reason.
- Selected signal and its selection explanation.
- Human-editable draft with visible **Review Required** state; no auto-send.
- History: runs, timestamps, final statuses, and saved outputs.

### MVP acceptance criteria

- A new, non-hardcoded prospect input reaches a real final outcome.
- For a valid signal, the drafted personalization can be traced to a specific source passage.
- Missing/ambiguous/expired signals do not silently become factual claims.
- All stages and results are visible; repeat runs are stored.
- One normal run + 2–4 prepared edge-case runs can be demonstrated reliably.
- Demo video <=5 minutes and both submission links are accessible.

## 9) Decision log

| Decision | Current status | Rationale |
|---|---|---|
| Choose PS-3 | **LOCKED** | User explicitly chose it. |
| Optimize for ~48-hour sprint | **LOCKED** | Tight deadline; prioritize runnable end-to-end workflow. |
| Hypothetical product: support triage copilot | **PROVISIONAL** | Creates coherent meaning for signal relevance tests. |
| Research strategy: targeted public web search | **PROVISIONAL** | Lower implementation cost vs crawling. |
| Research API: Tavily first | **PROVISIONAL** | Official SDK supports search/extract and keyless trials. |
| Hard validity checks + LLM relevance | **PROVISIONAL** | Separates factual eligibility from subjective business fit. |
| Auto-send | **EXCLUDED** | Not required and human review explicitly required. |
| UI: Streamlit | **PROVISIONAL** | Quick stages/status and form. |
| 3 edge cases | **PROVISIONAL** | Covers independent realistic failure classes. |

## 10) Open questions ordered by urgency

1. Does Tavily (keyless or keyed) work with our runtime, and can it retrieve adequate source text for Supabase and two other companies?
2. Which LLM/API is already accessible for structured fact extraction and drafting, and how will responses be validated against evidence?
3. Can the chosen UI and persistence survive a hosted demo, including refresh and cold starts?
4. What is the exact target persona for named-prospect identification? If no verified person identity exists, use a role-level email draft with no invented name.
5. Which additional edge-case test inputs can be run live with reproducible results?

## 11) Known limitations / honest demo narration

- The current research is based on source review plus local fixture tests, **not** a live operational prototype.
- A job posting can establish described responsibilities, not actual pain points or buying intent.
- Retrieval time is not publication date.
- Exact quote matching is a thin validation layer; semantic paraphrases and authenticity need further checks.
- Fictional test cases must be labeled synthetic; do not present them as public-company facts.
- Use plain language to explain when the system rejects evidence rather than pretending it is confident.

## 12) Update protocol

After each concrete test, append: **date**, **hypothesis**, **input**, **observed result**, **failure/limitation**, **decision change**, and **next action**. Do not promote a proposed feature to `TESTED` without executing it. Update this file explicitly when new work is done; it does not update itself in the background.

---

## 13) Implementation checkpoint — 12 Nov 2026 (current turn)

**New deliverable:** `ps3_signal_to_draft/` functional Python + Streamlit starter implementation.

### Verified results (executed locally)

- `TESTED OFFLINE`: Python modules compile: `core.py`, `services.py`, `fixtures.py`, `history.py`, `cli.py`, and `app.py`.
- `TESTED OFFLINE`: `pytest -q` returned **11 passed** using the test cases in `tests/test_pipeline.py`.
- `TESTED OFFLINE`: four CLI end-to-end runs completed using **synthetic sources** and **rules-based extraction/draft fallback**:

| Scenario | Observed status | Observed behavior |
|---|---|---|
| `happy` | `draft_ready` | Source retrieved from synthetic fixture, exact passage validated, candidate ranked, draft produced for human review |
| `stale` | `insufficient_evidence` | Explicit expired closing date excluded, draft blocked |
| `ambiguous_identity` | `needs_clarification` | Named prospect not associated with target official domain, draft blocked |
| `no_evidence` | `insufficient_evidence` | No source results, draft blocked |

- `TESTED OFFLINE`: SQLite persisted the four run results and returned them in newest-first order.
- `NOT TESTED`: Streamlit UI rendering and interaction; Streamlit package is not installed in this environment.
- `NOT TESTED`: Tavily API retrieval; DNS resolution to `api.tavily.com` fails in this environment. No key is configured. SDK not installed here.
- `NOT TESTED`: OpenAI model extraction/drafting; no `OPENAI_API_KEY` is configured. SDK functions were implemented following documented structured-output patterns but have not been executed against a live model.

### Files / code organization

- `core.py`: pipeline, source association, quote membership, deadline/recency gate, relevance ranking, status transitions.
- `services.py`: Tavily research adapter; OpenAI structured extractor/drafter; deterministic fallback components.
- `fixtures.py`: fictional test inputs and invented company URLs (synthetic; NOT real external sources).
- `app.py`: Streamlit UI with run events, evidence inspection, editable draft, review notice, run history.
- `cli.py`: command line runner with `--mode demo|live`, `--scenario`, and `--ai` options.
- `history.py`: local SQLite persistence.
- `tests/`: 11 passing unit/integration-style offline cases.
- `README.md`: setup, command examples, architecture, limitations, demonstration instructions.

### Decision changes

- `IMPLEMENTED OFFLINE`: Sequential pipeline rather than multi-agent orchestration, so each step is inspectable.
- `IMPLEMENTED OFFLINE`: Deterministic fallback lets the basic pipeline run even without model/network keys; **this fallback must not be described as an AI-generated output**.
- `IMPLEMENTED OFFLINE`: Separate named-prospect ambiguity status and insufficient-evidence status; never send automatically.
- `PROVISIONAL`: Tavily + OpenAI models for live mode remain integration candidates, not validated dependencies.

### Risks and next mandatory validation

1. Install the dependencies in a network-enabled environment, run `pytest -q`, then `streamlit run app.py` and verify the actual interface.
2. Run `python cli.py --mode live --company Supabase --domain supabase.com --ai` after providing appropriate keys. Inspect whether real sources provide usable evidence, and measure latency and outcomes. No successful live run is established yet.
3. Inspect generated messages for factual entailment, relevance and tone; a substring-match eligibility gate cannot guarantee an LLM paraphrase is truthful.
4. Deploy with secured API secrets and durable storage if past-run history must survive restarts; SQLite is not reliably persistent on ephemeral hosts.
5. Capture a real successful live run and prepared edge cases for the 5-minute demo.

**Truth constraint:** A passing fixture test does not establish real-world web retrieval quality, deployed availability, or production-grade fact checking.
