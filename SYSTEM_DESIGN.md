# PS-3 System Design — Prospect → Evidence-Grounded Outreach Draft

**Status:** `PROPOSED` design, 12 Nov 2026. Supersedes the architecture sections of `PS3_Latest_Research_Log.md`.
**Basis:** three research passes, covering 14 commercial tools, 17 open-source repos (source code read), and about 30 engineering and research write-ups. Sources are in §15.

**Labels:**
- `[R]` = a source reports it.
- `[VC]` = a vendor's marketing claim.
- `[I]` = our own design inference.
- `NOT TESTED` = a spike is still needed.

---

## 0. What this system is, in one paragraph

A sales rep enters a prospect (a person and a company). The system first confirms we have the right person at the right company. A **bounded research loop** then gathers signals over repeated rounds: a lead agent plans the searches, parallel workers run them, a reflector looks for gaps, and the loop goes round again. Every signal goes into a **ledger** with an exact quote, a URL and a date, and code checks each quote. The system then picks the hook that best fits **the seller's own offer**, writes a short email that may use only signals from the ledger, and has a separate verifier check every claim in that email. Finally a human reviews each sentence next to its evidence. Nothing is sent automatically. When the evidence is weak, wrong or risky, the system says so and stops or asks. It never invents a hook.

**Why this beats what exists today.**
- No open-source sales agent we read stores a quote, a URL and a date for each claim, or checks the email against its evidence [R: open-source review].
- Clay's agent does not return source URLs by default, and users report that it "makes things up" [R].
- 11x does attach a citation to every finding [R] but does not check those citations automatically.
- No vendor documents how it handles sensitive news such as layoffs, lawsuits or deaths [R: commercial review].

These are the gaps we close.

---

## 1. Design principles (and where each comes from)

| # | Principle | Source |
|---|---|---|
| P1 | Use fixed code where the logic can be fully specified. Use the LLM only for judgment calls. Give each agent one narrow job. | Clay docs [R]; Anthropic "Building effective agents" [R] |
| P2 | Research produces an argument, and every finding in it carries a citation. | 11x Deep Research docs [R] |
| P3 | Scale research effort to the prospect. Small prospects get small budgets, and no 50-subagent explosions. | Anthropic multi-agent research system [R] |
| P4 | Start wide, then narrow. Steer toward first-party and primary sources. | Anthropic [R]; Tavily curator [R] |
| P5 | Agents pass short structured findings between steps, not raw tool output. Carry reflections forward, not whole pages. | Tavily research blog [R]; Anthropic context engineering [R] |
| P6 | Every loop has a hard budget. When the budget runs out, the agent must answer with what it has (Jina calls this "beast mode") and must never invent anything. | Jina DeepResearch [R] |
| P7 | Verify facts one at a time, with a verifier that does not see how the draft was reasoned. | FActScore, SAFE, Chain-of-Verification [R] |
| P8 | Content fetched from the web can carry hidden instructions to the model (prompt injection). Anything that reads such content must be unable to trigger actions with consequences. | Simon Willison, "lethal trifecta" [R] |
| P9 | Autonomy is granted in stages: review every email first; autopilot only per segment, and only after quality has been validated. | 11x, HubSpot, Artisan docs [R] |
| P10 | The seller's knowledge base includes an explicit list of claims never to make, has an owner, and is versioned. | 11x knowledge-base docs [R] |
| P11 | Personal, family and private-intent signals never appear in the copy. | Practitioner and vendor blogs [R]; Leadpipe [R] |
| P12 | The email must fail the "one-field swap" test: it should not still make sense if only the prospect's name were changed. | getscaled [R] |

---

## 2. End-to-end flow

```
                    ┌────────────────────── SELLER WORKSPACE ──────────────────────┐
                    │ Seller profile (versioned): offer, ICP, personas, pains,     │
                    │ signal→pain map, approved claims, NEVER-claims, tone, footer │
                    └──────────────────────────────┬───────────────────────────────┘
Prospect input ──▶ S0 Intake & normalise
(name, company,      │
 domain?, title?,    ▼
 LinkedIn URL?)    S1 Pre-flight gates (fixed rules, cheap)   ── fail ──▶ BLOCKED_SUPPRESSED / DUPLICATE /
                     │  suppression · duplicate · recently contacted ·      RECENTLY_CONTACTED / INVALID_INPUT
                     │  jurisdiction flags · input validity
                     ▼
                   S2 Entity resolution (company → person)    ── ambiguous ──▶ NEEDS_CLARIFICATION (run pauses for rep)
                     │  first-party site = ground truth                ── moved ─────▶ CONTACT_MOVED (offer retarget)
                     │  person ↔ company ↔ title match                 ── not ICP ───▶ NOT_A_FIT (rep can override)
                     ▼
                   S3 RESEARCH LOOP  (lead/reflector + parallel workers, rounds 0..N)
                     │  output: Evidence Ledger (quote · URL · dates · entity match)
                     ▼
                   S4 Verify evidence (fixed rules + small LLM checks)
                     │  quote present · claim entailed · entity · dates · source quality · sensitivity
                     ▼
                   S5 Hook scoring & selection (LLM scores each dimension, code sums them)
                     │                                                 ── nothing above bar ─▶ LOW_SIGNAL
                     ▼                                                    (fallback ladder or "don't send")
                   S6 Draft (top hook + 2 alternates prepared)
                     ▼
                   S7 Fact-check draft (claim-by-claim, verifier blind to draft reasoning)
                     │  unsupported → minimal edit / regenerate (≤2) → else flag the sentence
                     ▼
                   S8 Human review: approve · edit · swap hook · regenerate · reject(reason)
                     ▼
                   S9 Output: copy / export / (later) push to Gmail-Outlook DRAFTS, CRM log
```

**Rules that hold for every run:**
- S1–S9 are each a durable step: a crash resumes from the last finished step instead of starting over.
- Every stage writes `stage_events` records, which drive the live run view.
- Every LLM call is traced: prompt version, model, tokens, cost and latency.

---

## 3. The research loop (S3) in detail

This answers the question of how research should repeat. The answer is a **recurring loop of agents, kept within hard limits**. We combine "parallel fan-out" in round 0 with "reflect on gaps, then search again" in rounds 1–N. We avoid recursive breadth/depth trees: the open-source repos that use them suffer exponential call counts, queries that drift off topic, and runs that take minutes [R: dzhng/deep-research, gpt-researcher deep mode].

### 3.1 Roles

| Role | Model | Job | Tools |
|---|---|---|---|
| **Lead researcher** (planner and reflector) | `judge` role (Groq gpt-oss-120b, see §10.0) | Writes the research brief and the round-0 query plan. After each round, reads the ledger and decides what is still missing. Decides whether to stop. | None. Its output is structured data only. |
| **Search workers** (parallel) | Code only in round 0. Bounded ReAct sub-agents in Deep tier gap rounds. | Run queries using provider filters, rank and deduplicate URLs, fetch pages | `search`, `fetch_page` |
| **Reader/extractor** (one call per page, run in parallel) | `reader` role (Gemini Flash-Lite) | Turns a page into candidate signals, each with a verbatim quote | None. Structured output only. |
| **Critic** (part of S4) | `checker` role (a different model family from the drafter), escalating to `judge` on disagreement | Flags stale signals, entity mismatches, speculation or marketing language, and aggregator sources | None |

The lead agent never reads raw pages. It sees only the compact ledger, which keeps its context small [R: Tavily, Anthropic].

### 3.2 State: an Evidence Ledger, not a running summary

Running summaries lose track of which claim came from which source [R: local-deep-researcher]. Instead, every item in the ledger is a record like this:

```python
class Evidence(BaseModel):
    id: str                      # short id "e7" — model cites ids, never raw URLs (Gemini quickstart trick)
    category: SignalCategory     # see 3.3
    about: Literal["person", "company", "market"]
    claim: str                   # one atomic fact, our words
    verbatim_quote: str          # ≤300 chars, exact text from page
    url: str; publisher: str; source_type: SourceType  # first_party | press | filing | aggregator | social | job_board
    published_at: date | None    # when the page says it was published
    event_date: date | None      # when the thing happened (may differ)
    retrieved_at: datetime
    entity_match: Literal["confirmed", "probable", "ambiguous", "mismatch"]
    quote_verified: bool         # set by code, not the model
    entailment: Literal["supported", "partial", "unsupported"] | None
    sensitivity: Literal["none", "negative_news", "personal", "private_intent"]
    round_found: int
```

Alongside the ledger, the run keeps:
- `queries_run[]` with their embeddings;
- `urls_seen{}`;
- `coverage{category → status}`;
- `budget{searches, reads, tokens, seconds}`.

### 3.3 Signal categories (the coverage checklist)

**About the person:**
- `role_change`: new role or promotion, plus tenure.
- `own_content`: posts, articles, talks, podcasts.
- `press_quote`: quoted in an article.
- `award_or_speaking`: awards or speaking slots.

**About the company:**
- `funding_mna`: funding rounds, mergers and acquisitions.
- `leadership_hire`: senior appointments.
- `hiring_pattern`: job postings, which reveal priorities. 11x calls these "the highest-signal public source" [R].
- `product_launch`: new products or features.
- `expansion`: new regions or legal entities.
- `partnership`.
- `tech_stack_change`.
- `strategy_earnings`: strategy statements and earnings (public companies).
- `regulatory`: regulatory events.

**Negative news (collected but blocked from use as a hook, see S4):**
- `layoffs`, `litigation`, `breach`, `death_or_tragedy`, `scandal`.

The seller profile's **signal→pain map** says which of these categories matter for this seller, and the lead agent sets research priorities from it.

### 3.4 One run of the loop

```
Round 0 — FAN-OUT (no agent loop; predictable latency)
  Lead: brief + 6–10 queries, ONE entity–attribute per query (Together AI prompt rule),
        each with a stated research_goal (dzhng pattern)
  Workers (parallel, 8–10 s timeout each):
     provider filters: entity name must appear in page (Exa includeText), category=news where relevant,
                       date window (default 12 mo), exclude seller's own domain, ≤2 results per host (Jina)
     URL ranking: first-party always kept (Tavily curator) > primary press/filings > others; dedupe vs urls_seen
  Readers (parallel): page → candidate Evidence; code checks quote ⊂ page text (normalised) → else drop
  ─────────────────────────────────────────────────────────────────────────────────────────
Round k ≥ 1 — REFLECT → TARGETED SEARCH
  Lead/Reflector gets: ledger (compact), coverage, remaining budget + remaining seconds (Firecrawl ODR pattern)
  returns {is_sufficient, missing_categories[], follow_up_queries[≤3], rationale}
  New queries are de-duplicated against queries_run (local fuzzy token similarity; Jina uses embedding cosine ≥ 0.86)
  Standard tier: workers run them (code). Deep tier: each gap becomes a bounded ReAct sub-agent
  (objective + output schema + source heuristics + ≤8 tool calls + stop rule — Anthropic delegation spec)
  ─────────────────────────────────────────────────────────────────────────────────────────
STOP when ANY holds:
  (a) coverage met: ≥1 verified person-level item AND ≥2 verified company-level items,
      ≥1 of them inside its recency window AND mapped to a seller pain
  (b) reflector says sufficient
  (c) diminishing returns: <2 new verified items last round, or ≥70% of new URLs already seen
      (open_deep_research "last 2 searches similar" rule)
  (d) budget hit (searches / reads / tokens / wall clock) or 2 consecutive failed rounds
  On (d): BEAST MODE — finalise from the ledger as-is; categories with nothing are marked "no signal found"
```

### 3.5 Effort tiers (Anthropic effort scaling)

| Tier | When to use it | Rounds | Searches / page reads | Sub-agents | Wall-clock target |
|---|---|---|---|---|---|
| **Quick** | Batch mode, low-value accounts | Round 0 only | ≤8 / ≤10 | none | ~30 s |
| **Standard** (default) | One-off prospects | 0 + up to 2 reflection rounds | ≤20 / ≤25 | none (code-driven workers) | ~60–90 s |
| **Deep** | Strategic accounts, executives | 0 + up to 3 reflection rounds | ≤35 / ≤40 | ≤3 concurrent, ≤8 tool calls each | ≤3 min |

Every number in this table is a starting default to be tuned with evals (§11). `NOT TESTED`

### 3.6 Failure modes copied from the repos, and how we mitigate each

- **Looping and redundant searches:**
  - Deduplicate queries by embedding similarity.
  - Keep a shared `urls_seen` across all workers.
  - Add a nudge to the reflector: "you've tried these angles; pick a different one or stop" [R: Jina diary].
- **Query drift:** every query is tied to one signal category and the entity's name. The reflector may only propose queries for categories still missing.
- **Too many sub-agents:** a hard cap on concurrency. Extra spawn requests come back as errors [R: open_deep_research].
- **Context bloat:** the lead agent sees only the ledger. Full page text is stored by reference and fetched only when needed.
- **Broken structured output:** retry up to 3 times with the validation error included, then fall back to a degraded but valid output [R: open_deep_research].

### 3.7 Free first-party signal connectors (higher quality, zero quota)

Search APIs are the expensive, generic path, so workers try **direct, free, authoritative sources first** and use search credits only for what those can't cover. All of these are `NOT TESTED`; they are public endpoints or feeds to confirm in the Phase-0 spike.

| Signal | Free source | Why it's better |
|---|---|---|
| Company news, launches, funding | Company `/press`, `/blog`, `/news`, `/changelog`, found via `sitemap.xml` and RSS/Atom feeds | First-party ground truth with real publish dates |
| Third-party news | Google News RSS search for `"Company"` | Dated items from many publishers, no key needed |
| Hiring | Public job-board APIs: Greenhouse, Lever, Ashby (no key) | Structured postings with dates and live/closed status. Better than scraped job aggregators. |
| Public-company strategy | SEC EDGAR (free; requires a User-Agent) | Authoritative filings and dates |
| Person's talks and podcasts | iTunes/Apple Podcasts Search API (free), YouTube RSS for known channels | Finds podcast episodes and talks with dates |
| Developer-tool companies | GitHub API (free; rate-limited) | Releases and activity with exact dates |
| Fetch and extraction | `httpx` + `trafilatura`; Jina Reader as a fallback for pages that need JavaScript | Free, and stores the text needed for quote checks |

**Per-company caching:** company-level research is cached (TTL 7 days), so a second prospect at the same company reuses it. That means faster runs, no extra quota, and the same facts every time.

---

## 4. Entity resolution (S2): the most important guardrail

Contacting the wrong entity is the commonest embarrassing failure reported: congratulating a company on a similarly named firm's milestone, or on a role the person has already left [R].

1. **Company.**
   - If the domain is known, fetch the homepage and about page as ground truth (Tavily pattern).
   - If only a name is given, search and cluster the results by domain:
     - one strong cluster → `confirmed`;
     - several clusters → `NEEDS_CLARIFICATION`, showing the top 3 candidates with evidence.
   - Detect subsidiary/parent relationships, rebrands and acquisitions from the first-party site and press.
   - Record `canonical_company{name, domain, aliases[], parent?}`.
2. **Person.**
   - Search for `"<name>" "<company>"`, and `"<name>" <title>`.
   - A LinkedIn URL, if supplied, is used only as an identifier inside queries. We do not scrape LinkedIn.
   - Score the match on: name + company + title + location, consistency across sources, and whether a first-party page (team page, press release) mentions them.
3. **Job-change detection.** If the best evidence (recent and from a credible source) places the person at a different company → `CONTACT_MOVED`. The run shows the evidence and offers: (a) retarget to the new company, (b) find the current person in this role at the original company (later phase), (c) stop.
4. **Same-name collision.** If two people share the name at different companies or in different roles and the company match is weak → `NEEDS_CLARIFICATION`. The run waits durably until the rep picks one, then resumes from S3.
5. **Every evidence item** gets `entity_match`. Only `confirmed` items may be hooks. `probable` items may support context. `ambiguous` or `mismatch` items are excluded.

---

## 5. Evidence verification (S4): code first, then the model

| Check | How it's done | If it fails |
|---|---|---|
| Quote is really on the page | **Code:** normalise whitespace, Unicode and quote marks, then do a substring or fuzzy match (ratio ≥ 0.95) against the stored page text | Drop the item |
| Claim is supported by the quote | **`checker` model**, one claim at a time (FACT/SAFE style): supported / partial / unsupported | Unsupported → drop. Partial → rewrite the claim to match the quote, or drop. |
| Entity | From S2, plus "does the quote mention the entity or an alias?" | Exclude from hooks |
| Dates | Code: `published_at` and `event_date` parsed; relative dates ("last week") anchored to the publication date; republished aggregator copies resolved to the earliest primary date | Undated → **timeless wording only**, never "recently" or "just" |
| Recency window | Code: per-category windows set in the seller profile (defaults below) | Outside the window → stays in the ledger as context, scores lower, and may not be described as recent |
| Source quality | Rules: first-party > filing > reputable press > job board > social > aggregator or SEO farm. Flags speculative language ("could", "may"), projections and marketing spin [R: Anthropic cookbook] | Aggregator-only facts need a second source before they can be the hook |
| Sensitivity | `checker` classifier plus keyword rules → negative_news / personal / private_intent | **Blocked as a hook.** Negative news may still inform tone (e.g. don't pitch cost-cutting tools in the week of a layoff); see §8 |
| Conflicting sources | Two items contradict each other (e.g. different funding amounts) | Prefer the primary source. Never use the disputed number in the email. Flag it to the rep. |

**Default recency windows** (configurable). The vendor claims about signal decay are unverified [VC], so these are our own judgment:

| Signal | Window |
|---|---|
| role_change | ≤ 120 days |
| funding_mna | ≤ 180 days |
| hiring_pattern | posting still live, or ≤ 60 days old |
| product_launch, expansion | ≤ 180 days |
| own_content, press_quote | ≤ 12 months |
| Responsibilities in a job post | Evergreen: allowed, but with no recency wording |

---

## 6. Hook scoring and selection (S5)

The `judge` LLM scores each eligible item from 1 to 5 on every dimension and gives a one-line reason for each. **Code computes the weighted total.** The weights live in the seller profile, so they are explicit and can be tuned.

| Dimension | Question asked |
|---|---|
| Offer relevance | Can we write one honest sentence linking this signal to a pain in the seller profile? |
| Specificity | Does it fail the one-field swap? Is it about *this* person or company rather than the industry? |
| Recency | How far inside its category window is it? |
| Persona fit | Company-level hooks suit directors and above; personal hooks suit individual contributors and managers. This is a prior from Gong data [VC] and is tunable. |
| Source strength | Primary source, and corroborated? |
| Closeness to the person | Did the person do it, their team, or the company? |

**Hard vetoes** apply before any score is computed: sensitivity ≠ none, entity ≠ confirmed, quote not verified, or entailment = unsupported.

**Output:** the top hook and two alternatives, each with its score breakdown, so the rep can switch hooks in review.

**Fallback ladder** when no item clears the threshold:
1. A weaker but valid company-level hook, labelled **Low confidence**.
2. A role or industry angle with cited peer or industry proof. Gong reports +88% for this, but it is a vendor claim [VC].
3. `LOW_SIGNAL`: "Not enough to personalise. Sending a generic email will hurt more than help." Fake personalisation can underperform no personalisation at all [R].

---

## 7. Drafting (S6) and fact-checking (S7)

### 7.1 Draft rules (from the seller profile, with these defaults)

- **Length:** ≤100 words, 3–4 sentences. Gong reports that ≤100 words and 3–4 sentences perform best [VC]. Instantly reports that the best campaigns stay under 80 words [VC].
- **Structure:**
  1. The observation, which must cite an evidence ID.
  2. Why it made us think of them.
  3. One line linking to the offer, drawn **only** from the approved claims.
  4. A low-friction ask. For executives, offering an insight or benchmark works better than asking for a meeting [VC: Gong].
- **No heavy pitching.** Gong reports that pitching cuts reply rates by up to 57% [VC]. No buzzwords or numbers in the subject line.
- **Banned:**
  - invented metrics;
  - "I loved your post" unless we hold that post as evidence;
  - recency words without a dated item;
  - personal or family references;
  - any never-claim from the seller profile.
- **Language:** the prospect's language if known, otherwise the workspace default. Non-English sources are allowed. Quotes are kept in the original language, and the claim is translated.
- **Footer (per workspace, configurable):** a working opt-out and the sender's postal address, which CAN-SPAM requires [R]. Optionally, a GDPR Art. 14 notice saying where the data came from and the right to object [R: ICO, IAPP]. *This is not legal advice; the customer is responsible for compliance.*

The drafter receives evidence only by **short ID** and must cite IDs inline. Code then renders those IDs into hover-citations in the review screen.

### 7.2 Fact-check

1. **Break the draft into atomic claims** (FActScore/SAFE). Each claim is one of:
   - a prospect fact, which must map to an evidence ID;
   - a seller claim, which must match the approved claims;
   - a pleasantry or ask, which has nothing to check.
2. **Factored verification** (Chain-of-Verification). Each claim is checked in its own call against **only** the cited quote. The verifier never sees the draft's reasoning, so it cannot repeat the drafter's hallucination [R].
3. **Fixed-rule checks:**
   - names are spelled as in the evidence;
   - numbers and dates match the evidence exactly;
   - word and sentence counts;
   - banned phrases and never-claims (regex plus a list);
   - the footer is present;
   - no URL that isn't in the evidence.
4. **Fixing unsupported claims:** minimally edit just the unsupported span (RARR style) and re-verify. Allow at most 2 rounds. If it still fails, keep the draft but **highlight the sentence red**; it cannot be approved until it is edited.
5. **Integrity check on the citation pass** [R: Anthropic citations_agent]: the verifier may only add or remove citation IDs or delete spans. Any other change to the text is rejected.

**Known gap:** a precision-only metric like FActScore rewards vague emails [R]. So we also score specificity (§6) and track how often signals from the golden set are recovered (§11). Without both, the system could game itself by saying less.

---

## 8. Edge-case catalogue: every condition and how it's handled

★ = demo edge case (4 chosen). **State** = the run's final status shown in the dashboard.

### 8.1 Input and pre-flight
| # | Condition | Detection | Behaviour | State |
|---|---|---|---|---|
| 1 | Missing or garbage input (no company; a name like "test") | Validation | Reject with a field-level message | `INVALID_INPUT` |
| 2 | Only a company given, no person | Input shape | Suggest the best-matching person for the campaign's target persona from public first-party sources (team or leadership page, press releases naming people). **The rep confirms before research continues.** If no one is found → a role-level email to the persona. Never invent a name. | `NEEDS_CLARIFICATION` (confirm the contact) |
| 3 | Prospect is on the suppression or do-not-contact list | Pre-flight lookup (also re-checked at export or send time [R: Unify, HubSpot]) | Stop before any research. Spend nothing. | `BLOCKED_SUPPRESSED` |
| 4 | Duplicate prospect, in a batch or researched recently | Hash of normalised name + domain; recent-run lookup | Reuse the recent ledger if it's within its TTL, or skip | `DUPLICATE` |
| 5 | Contacted recently, or a colleague at the same account was emailed in the last N days | History lookup | Warn. Avoid a same-hook collision across the account (multi-threading) [R: 11x] | `RECENTLY_CONTACTED` (rep can override) |
| 6 | Jurisdiction needs consent (e.g. Germany, where UWG §7 generally requires consent for B2B email [R, verify with counsel]); sole trader under UK PECR [R] | Country from domain or company evidence | **Flag** in review; the workspace policy decides whether to block or warn | flag |

### 8.2 Identity
| # | Condition | Behaviour | State |
|---|---|---|---|
| 7 ★ | **Prospect has moved companies** (stale CRM data; contact data reportedly decays ~20–30% a year [R, primary source unverified]) | Show the evidence of the new role and offer to retarget. No draft to the old company. | `CONTACT_MOVED` |
| 8 ★ | **Same-name person or company collision** | Cluster by domain and entity, show candidates; the run pauses durably and resumes on the rep's pick | `NEEDS_CLARIFICATION` |
| 9 | Subsidiary vs parent, rebrand, acquisition | Map to the canonical entity, keeping aliases. Hooks name the entity the prospect actually works for. | normal |
| 10 | Person can't be found at all | Company-level research only, with a role-level draft and an explicit note | normal / `LOW_SIGNAL` |
| 11 | Company outside the ICP (size, industry, region) | Fit check against the seller profile, with reasons | `NOT_A_FIT` (rep can override) |
| 12 | Prospect works at an existing customer or open deal (once a CRM is connected) | CRM lookup | `BLOCKED_EXISTING_RELATIONSHIP` |

### 8.3 Evidence and dates
| # | Condition | Behaviour |
|---|---|---|
| 13 | Quote not found on the page (the model paraphrased or hallucinated it) | Dropped by code. The reader gets an error and can retry once. |
| 14 | Page is undated | Allowed only with timeless wording. Recency words are blocked by the fact-check. |
| 15 | An aggregator republished old news with a fresh date | Resolve to the earliest primary date. If unresolvable, treat it as undated. |
| 16 | Relative dates ("next quarter", "last week") | Anchored to `published_at` |
| 17 | Sources conflict (funding amount, title) | Prefer the primary source. Never use the disputed fact in the email. Flag it. |
| 18 | Paywall, 403, JS-only page, timeout | Try the provider's live crawl, then a direct fetch with text extraction, then skip with a logged reason. Never guess the content. |
| 19 | SEO farm or AI-generated company profile is the only source | Ranked lowest. Can't be the hook without a second source. |
| 20 | Page changed between retrieval and review | A snapshot is stored; the review shows `retrieved_at`. Optionally re-fetch before export (§5). |
| 21 | Non-English sources | Allowed. Quote kept in the original language, claim translated, language tagged. |
| 22 | The research keeps hunting for sources that don't exist | Stop rules (c) and (d), then beast mode. Missing categories are recorded as "no signal found". |

### 8.4 Hook judgment
| # | Condition | Behaviour | State |
|---|---|---|---|
| 23 ★ | **The strongest or most recent signal is sensitive** (layoffs, lawsuit, breach, death, scandal) | Vetoed as a hook. The next-best hook is chosen, with an explanation. Tone guidance changes (no cost-cutting pitch during layoffs). If only sensitive signals exist → hold for a human. | normal + explanation / `NEEDS_REVIEW_SENSITIVE` |
| 24 | Creepy signals: personal life, family, private intent such as pricing-page visits | Personal signals are never collected as hooks. Private intent, if integrated later, is used **only for timing**, never in the copy [R]. | — |
| 25 ★ | **Thin signal** (low-profile person, small private company) [R: 11x FAQ] | Fallback ladder (§6), labelled with confidence. Below the floor → recommend not sending. | `LOW_SIGNAL` |
| 26 | True but irrelevant signal (nothing to do with the offer) | Low offer-relevance score. Not used even if it's very recent. | — |
| 27 | Executive persona | Prefer company-level hooks and an insight-style ask; shorter | — |
| 28 | Batch output sounds the same | Batch check: flag when any 5 consecutive drafts share structure or openers above a similarity threshold [R: 11x] | flag |

### 8.5 Seller side
| # | Condition | Behaviour |
|---|---|---|
| 29 | The draft makes a product claim not in the approved list | The fact-check flags it. It cannot be approved until edited. |
| 30 | The draft makes a never-claim (guarantees, ROI numbers, a competitor's name) | Blocked by fixed rules and the verifier |
| 31 | Seller profile is stale or was edited during a batch | Each run stores the `profile_version` it used. Changes are not applied retroactively (Apollo does the same [R]). Show the review-by date. |
| 32 | Seller profile is too thin to judge relevance | Profile-completeness gate at setup. Runs warn: "relevance scoring unreliable". |

### 8.6 Adversarial and reliability
| # | Condition | Behaviour |
|---|---|---|
| 33 | **A web page contains hidden instructions** ("ignore previous instructions…") | Readers have no tools and produce structured output only. The recipient and allowed actions are fixed *before* research starts. Quotes are checked by code. Nothing in research can send or write externally. Worst case: a bad candidate signal that verification rejects [R: Willison patterns]. Test page in the eval set. |
| 34 | LLM or search API rate limit, 5xx, timeout | Per-provider queue rate limits; retries with backoff; a durable step resumes after a crash. If a provider stays down → `FAILED` with the reason, or Tavily is used as a fallback provider. |
| 35 | Worker crashes mid-run | DBOS resumes from the last completed step. Idempotency key `{run_id}:{stage}:{n}` means no repeat spend. |
| 36 | Structured output fails to validate | Retry up to 3 times with the validation error. If it still fails, the step fails with an explanation. |
| 37 | Cost or latency exceeds the per-run budget | Hard caps → beast mode. Cost is shown per run. |
| 38 | Model refusal | Refusal fallback; logged. The run fails cleanly if it isn't recoverable. |
| 39 | The same run is triggered twice (double-click, a retried request) | Idempotent run creation (client request ID) |
| 40 | Data subject asks to be erased, or the retention window has passed | Delete by prospect; scheduled purge (§12) |

---

## 9. Seller profile (workspace knowledge base)

The seller is the customer using the product, so they configure this profile, not us. It can be **auto-drafted from their website** and is then edited and approved by them. It is versioned, with an owner and a review-by date [R: 11x].

```yaml
company: {name, domain, one_liner}
offer: {product, problem_solved, how_it_works_plain}
icp: {industries[], employee_range, regions[], exclusions[]}
personas: [{title_patterns[], seniority, pains[], hook_preference: company|individual}]
signal_to_pain: {hiring_pattern: [...pains], funding_mna: [...], expansion: [...], ...}
approved_claims: [{claim, proof_url?}]
never_claims: ["guaranteed ROI", "specific % savings", competitor names, ...]
tone: {voice, formality, max_words: 100, cta_style: soft|direct}
recency_windows: {...overrides}
hook_weights: {...overrides}
compliance: {footer, art14_notice: bool, blocked_jurisdictions[], suppression_list_ref}
version, owner, review_by
```

### 9.1 Campaign layer: why we are reaching out

```
Seller profile (once, versioned)  → WHO we are: offer, ICP, personas, pains, approved / never claims, voice, compliance
   └─ Campaign (per goal)         → WHY now: objective, target persona/segment, CTA, angle, signal priorities, tone tweak
        └─ Prospect run           → WHO specifically: research → hook → draft → review
```

```yaml
campaign:
  name: "Q1 AP-automation demos — Series B fintechs"
  objective: "Book 20-min demos with finance leaders feeling AP pain from growth"
  target: {persona_ref: "vp_finance", segment: {industries: [fintech], stage: [series_b, series_c], regions: [US, UK]}}
  angle: "Scaling headcount without scaling AP team"
  cta: {type: soft_question, example: "Worth a quick look?"}
  signal_priorities: {hiring_pattern: high, funding_mna: high, expansion: medium}
  claims_to_emphasise: [<ids from profile.approved_claims>]
  extra_never_claims: ["no mention of competitor X"]
  tone_adjustment: "slightly more direct"
  profile_version: 7          # pinned; changes are not retroactive
```

**Rule: the profile is the source of truth for facts and limits. The campaign sets focus and intent. A campaign can narrow, focus and add restrictions. It can never contradict the profile or loosen a safeguard. Neither silently overwrites the other.**

| Field | Merge rule |
|---|---|
| Product claims | The campaign can only **select or emphasise** claims from `profile.approved_claims`. A new claim must be added to the profile first (versioned, with an owner). |
| Never-claims | **Union.** A campaign can add restrictions but never remove the profile's. |
| Target segment | Must fall inside the profile's ICP. If outside → flagged "outside ICP: confirm intentional" and recorded (e.g. testing a new segment). |
| Persona and pains | Campaign persona must exist in the profile. Pains = the profile's pains for that persona, plus the campaign angle. |
| Signal priorities and hook weights | The campaign adjusts the profile's defaults within bounds. **The sensitivity, entity and quote-verification vetoes can't be disabled.** |
| Tone | The campaign adjusts within the profile's brand voice. Hard limits (max words, banned phrases) stay. |
| Compliance footer, suppression | Profile or workspace level only. A campaign can't change them. |

**How the two layers support each other:**
- **Validation when a campaign is saved:**
  - Code checks: persona exists; segment is inside the ICP; emphasised claims exist; the CTA type is allowed.
  - An LLM consistency check reads the objective and angle and asks: is this supported by the approved claims? Does it imply a promise the profile forbids? Is any target signal mapped to a pain?
  - Each conflict is shown to the user with a suggested fix. **Nothing is auto-overwritten.**
- **Research is driven by both.** The research brief = campaign objective × the profile's signal→pain map, which gives which signals to hunt first and why they matter.
- **Scoring and drafting** score offer-relevance against *this campaign's* angle. Claims and limits come from the profile.
- **Effective brief.** Each run stores and displays the merged brief, with each field tagged by its source (`profile vN` / `campaign`), so the rep can see why the email says what it says.
- **Feedback flows back to the profile:**
  - If reps keep adding the same claim by hand, the system suggests adding it to `approved_claims`.
  - If a campaign's angle gets rejected repeatedly with the same reason, it suggests revising the angle.
  - These are **suggestions only**. The profile owner approves them.

### 9.2 Batch (CSV) mode

The brief's SDR has 200 prospects, so batch is a first-class input. Single entry stays for ad-hoc use and the live demo. Both feed the same per-prospect workflow.

1. **Upload and map:**
   - CSV/XLSX → column mapping (name, company, domain, title, LinkedIn URL, rep notes; extra columns kept as context).
   - Row validation, normalisation and deduplication, with a preview of problems before anything is spent.
2. **Pre-flight on every row** (free, no LLM): suppression list, duplicates, recently contacted, ICP fit (from the domain or company data where available).
3. **Group by company:** company-level research runs **once per account** and is shared by every prospect at that company. Prospect lists are often account-heavy, which saves a lot of quota.
4. **Two-pass triage:**
   - **Pass 1:** Quick tier for every row, using mostly the free first-party connectors.
   - This yields a **triage table** with hook strength, confidence and state for each row.
   - **Pass 2:** Standard or Deep tier only for the top N rows or the rows the rep selects. Low-signal rows are flagged "don't send generic" instead of being forced through.
5. **Quota-aware scheduling:**
   - DBOS queues process rows within each provider's free limits.
   - When daily quota runs out, the batch **pauses and resumes automatically** after the reset.
   - The UI shows progress, an ETA and "drafts ready by tomorrow 9am" style messaging.
   - A crashed batch resumes and never repeats completed rows.
6. **Batch review queue:**
   - Keyboard-driven, one prospect at a time: evidence on the left, draft on the right, `A` approve / `E` edit / `S` swap hook / `R` reject.
   - Sorted by confidence. A **sameness check** flags repetitive openers or structures across the batch.
   - **Every draft still needs an individual human approval.** There is no bulk send.
7. **Export:** CSV with draft, subject, hook, citations and state. Later: push to Gmail/Outlook **drafts** or a CRM.

**Free-tier reality (honest):** 200 rows at Standard depth is far beyond free daily limits. Estimate: about 200 × 60–90K tokens, and about 3,000 search credits against 1,000 a month. With the free tier:
- Pass 1 covers the whole list over about 1–3 days, depending on how many accounts repeat.
- Pass 2 goes deep on the best 20–40.

With paid keys the same code does 200 in one sitting, which is a config change. These estimates are `NOT TESTED`; Phase 0 measures them. **Demo:** a 10-row CSV including the edge cases.

---

## 10. Architecture and stack

| Layer | Choice | Why |
|---|---|---|
| Language | **Python 3.12** | Your preference. Pydantic models everywhere. |
| API | **FastAPI** | REST plus a live stream (SSE) of stage events |
| Orchestration | **DBOS** (Postgres-backed durable workflows, steps and queues) | Resumes after crashes, per-provider rate-limited queues, durable waits for the rep's input. No extra server. `NOT TESTED`: spike first. |
| Agents | **Plain Python + Anthropic SDK**, with structured outputs into Pydantic. No LangChain or LangGraph. | The loop in §3 is explicit code we can explain. Typed outputs. LangGraph's archived reference projects confirm the patterns but add nothing we need. |
| Models | **Free tier, routed by role (§10.0):** `judge` = Groq gpt-oss-120b; `reader` = Gemini Flash-Lite; `checker` = Groq Qwen (a different model family from the drafter); fallbacks: Mistral free tier → local Ollama | Judgment-heavy steps get the strongest free model; token-heavy reading goes to the provider with the most generous token limits. Switching to a paid model later is a config change. |
| LLM client | `openai` Python SDK pointed at each provider's OpenAI-compatible endpoint, plus **Instructor** (validated Pydantic outputs with retries), plus our own ~100-line router | One client for every provider. Moves to the next provider on 429/5xx. Rate limiting per provider. |
| Search | **Tavily** as the primary (free: 1,000 credits a month, `topic:"news"`). **Exa** free credits as the secondary (entity guardrails: `includeText`, `category:"news"`). `ddgs` (DuckDuckGo, no key) for development and as a last resort only. All behind a `SearchProvider` adapter. | `NOT TESTED`: bake-off on 10 prospects. Exa's free allowance is inconsistent across sources; confirm at signup. |
| Fetch and extract | Provider contents first. Otherwise `httpx` plus `trafilatura` for main-text extraction. Raw HTML and text stored. | Needed for quote checks and snapshots |
| Dedup and chunk selection | `rapidfuzz` (query and claim deduplication) and `rank_bm25` (choosing the most relevant passages of each page). Both run locally and are free. | Jina pattern without paid embeddings. Cuts the tokens sent to the reader model by roughly 70–80% [I]. |
| Database and auth | **Supabase free** (Postgres + Auth + Storage), row-level security per workspace. *(Full product only; v0 uses Neon, see §16.2.)* Local development uses Postgres in Docker. | Free projects pause after 7 days of low activity, so a GitHub Actions cron job pings the database daily. Alternative: Neon free, which wakes up automatically. |
| Page snapshots | Supabase Storage (by content hash) | Evidence survives page changes (edge case 20) |
| LLM tracing and evals | **Langfuse Cloud Hobby** (free: 50k units a month, 30-day retention) or self-hosted in Docker | Prompt versions, tokens, traces, datasets and judge scores |
| Frontend | **Next.js + shadcn/ui** as a thin client (no business logic) | The UI is graded. All logic stays in Python. |
| Hosting | **Render free web service** (FastAPI with DBOS running in the same process; free background workers aren't offered), **Vercel Hobby** (web), Supabase | Render's free tier spins down after 15 minutes idle and takes about 1 minute to start again, so warm it up before a demo. Don't use Render's free Postgres; it expires after 30 days. Vercel Hobby allows non-commercial use only. |
| Quality | pytest with **recorded real API responses** (VCR-style), ruff, mypy, GitHub Actions; the eval suite runs on prompt changes | Offline tests that use real data, not hand-made fixtures |

### 10.0 Free-tier constraint (decided 12 Nov 2026)

**Every service must be free, using only free tiers.** Claude Code is logged in with a claude.ai subscription. No Anthropic API key or `ant` login exists on this machine, and the Claude API is billed separately from the subscription. So the LLM layer uses free providers behind a router.

**LLM roles and fallback chains.** The limits below were checked on 12 Nov 2026 and change often, so re-check them in each console.

| Role | Used for | Primary | Fallback 1 | Fallback 2 |
|---|---|---|---|---|
| `judge` | Lead/reflector, hook scoring | Groq `openai/gpt-oss-120b` (strict JSON schema; free: 30 RPM, 1K RPD, 8K TPM, 200K TPD) | Gemini Flash (free, low daily requests) | Mistral free tier |
| `writer` | Email drafting (1–3 short calls per run, and the part the rep sees most) | **The strongest free model in the bake-off.** Candidates: Gemini 3.x Flash (free, low daily requests is fine here because calls are few), gpt-oss-120b, Mistral | Runner-up from the bake-off | gpt-oss-120b |
| `reader` | Page → evidence extraction (most of the tokens) | Gemini Flash-Lite (free tier, reportedly about 500 RPD [unverified]) | Groq `openai/gpt-oss-20b` (its own 200K TPD) | Local Ollama |
| `checker` | Claim-vs-quote checks, sensitivity, entity checks | Groq `qwen/qwen3.8-27b` (its own 200K TPD; a different model family from the drafter, so errors are less likely to be shared) | Gemini Flash-Lite | Local Ollama |

**Rejected options:**
- **Cerebras:** only a $5 trial that expires after 30 days, with no permanent free tier.
- **OpenRouter `:free`:** 50 requests a day unless you buy $10 of credits.
- **Brave Search:** now requires a card.

**Keeping within free limits ("token diet"):**
1. Never send whole pages to a model. Extract the main text with trafilatura, then send only the top BM25 passages (about 1,500 tokens per page) to the `reader`.
2. The lead agent sees only the compact ledger.
3. Each Standard run is estimated at about 60–90K tokens [I, `NOT TESTED`]. That allows roughly 8–15 Standard runs a day on free tiers, and more on Quick tier.
4. The search and LLM response cache plus **Replay mode** make repeated test and demo runs cost nothing.

**Making the demo reliable on free tiers:**
- Stop testing the day before the demo so daily quotas reset.
- Pre-run the demo prospects that morning so their results are cached.
- Use Replay as the safety net, clearly labelled when used.
- Warm up the Render service 2 minutes before starting.
- Check quotas in the Groq and AI Studio consoles.

**Caveats:**
- **Data use:** the Gemini free tier and Mistral's free plan may use your inputs to train or improve their models. We only send public web text and the seller profile. A real paying customer with a confidential profile needs paid, no-training tiers.
- **Quality:** open models judge less well than frontier models, which is one more reason the design relies on code-based checks. If the evals (§11) show a gap, upgrading is a change to `llm_roles.yaml`, not to code.

### 10.0b Quality and experience guarantees on free tiers

**Rule: free limits how much we can do, never how good it is.** Each run must meet the same quality bar a paid stack would. Where a free tier can't meet it, the system does fewer runs and does them well.

**1. Quality comes from the architecture, not raw model size:**
- Every LLM task is narrow (extract a quote, check a claim, score one dimension). Open models do these reliably.
- Strict JSON schemas and Pydantic validation with retries. Code-based checks (§5, §7) catch what any model gets wrong.
- A different model checks the writer's work, so errors are less likely to be shared.
- Each prompt has 2–3 worked examples (good and bad) drawn from the golden set.
- **Self-consistency on the decisions that matter:** hook scoring is sampled twice and the scores averaged. If the top hook differs between samples → a third sample breaks the tie. It's cheap because the inputs are compact ledgers.
- **Best-of-2 drafting:** the `writer` produces 2 drafts (each about 100 words, so cheap). The `judge` picks one against the rubric, and the other becomes the "alternative" in review.

**2. Quality gates.** A draft reaches the rep only if it passes all of these:
- Fact-check: 100% of prospect claims linked to verified evidence.
- Seller claims: only from the approved list.
- Style rules: word and sentence limits, no banned phrases, footer present.
- Rubric judge: specificity (one-field swap), relevance, tone and non-creepiness each pass.

If a gate fails → regenerate with the failure reason, at most twice. If it still fails → the rep sees an honest explanation ("couldn't produce a draft meeting the bar because…") and the evidence. **The rep never sees a weak draft presented as a good one.**

**3. Models are chosen by measurement.** A Phase-0 bake-off runs every free candidate for each role on the golden set. The winner per role goes into `llm_roles.yaml`. Any model or prompt change must pass the eval suite (§11) before merge. Release targets (initial; tighten later):

| Metric | Target |
|---|---|
| Draft claim precision | 100% |
| Quote verified rate | 100% of displayed evidence |
| Edge-case routing accuracy | ≥ 95% |
| Hook agreement with human pick | ≥ 80% (top-3 contains the human pick ≥ 95%) |
| Rubric pass rate | ≥ 85% |
| p50 / p95 run latency, Standard tier | ≤ 60 s / ≤ 120 s |

**4. Free first-party data sources raise quality and save quota (§3.7).** Company sites, job boards, news feeds and filings are fetched directly. They are more authoritative and better dated than generic search results, and cost nothing.

**5. The experience must not show it's free:**
- **No cold starts:** Render's free 750 hours a month covers one service running all month (744 hours), so a free uptime pinger keeps it awake. The pinger hits a health check that does **not** query the database, so Neon can sleep between real visits (its free plan has 100 compute-hours a month; awake around the clock would need about 180).
- **No raw errors:** a 429 or provider outage silently falls back to the next provider. The UI never shows a rate-limit error.
- **Quota-aware start:** before a run starts, the system checks remaining daily quota for the chosen tier. If it's short, it offers Quick tier or queues the run with an ETA, instead of failing halfway.
- **The wait feels useful:** the live view streams signals as they are found, and partial results are usable before the draft is ready. Groq's fast inference keeps judgment steps sub-second.
- **Batch runs** are queued within limits and framed as "drafts ready by morning", not as throttling.
- **Quota panel** on the dashboard: remaining daily requests and tokens per provider and search credits for the month.
- **Replay** is always labelled. It's a demo safety net, not a way to fake results.

**6. The honest limit:** free tiers bound **volume**: roughly tens of Standard runs a day and about 1,000 search credits a month, stretched by the free sources and per-company caching. That's comfortable for one rep, the tests and the demo. A team doing 200 prospects a day would need paid tiers, and that's a config change, not a redesign.

### 10.1 Repo layout

```
app/
  api/            runs.py, prospects.py, profiles.py, reviews.py, stream.py
  workflows/      prospect_run.py (DBOS workflow: S0–S9), batch.py
  stages/         intake.py, preflight.py, entity.py, research/, verify.py, score.py, draft.py, factcheck.py
  research/       lead.py, workers.py, reader.py, reflector.py, budget.py, ledger.py
  policy/         quotes.py, dates.py, sensitivity.py, recency.py, source_quality.py, banned.py
  providers/      llm_router.py, llm_roles.yaml, search/{tavily,exa,ddgs}.py, fetch.py, chunks.py, cache.py
  domain/         models.py (Prospect, Evidence, HookScore, Draft, Claim, RunState…)
  prompts/        versioned prompt files (lead, reflector, reader, scorer, drafter, verifier)
evals/            golden/, judges/, run_evals.py, reports/
web/              Next.js app
```

### 10.2 Data model (main tables)

| Table | Contents |
|---|---|
| `workspaces`, `users` | Accounts and membership |
| `seller_profiles` | Versioned profiles |
| `campaigns` | Objective, target, angle, CTA, priorities; `profile_version` pinned; `validation_report` |
| `batches`, `batch_rows` | Upload, column mapping, row status, triage pass, account group |
| `prospects` | Normalised inputs; `canonical_company`, `canonical_person` |
| `runs` | `state`, `tier`, `profile_version`, `budget_used`, `cost_usd`, timings |
| `stage_events` | `run_id`, `stage`, `type`, `payload`, `ts`; drives the live view |
| `evidence` | The ledger from §3.2; `snapshot_ref` |
| `hook_candidates` | Per-dimension scores and reasons |
| `drafts`, `draft_claims` | `claim → evidence_id`, `verdict` |
| `reviews` | Action, edited text, diff, reason |
| `llm_calls` | Model, prompt version, tokens, cost, latency, trace ID |
| `search_cache` | Provider + query hash → raw response, TTL; used for replay |
| `suppression_list` | Do-not-contact entries |
| `audit_log` | Audit trail |

### 10.3 Run states

**Pipeline outcomes:**
- `DRAFT_READY`
- `CONTACT_MOVED`
- `NEEDS_CLARIFICATION` (the run is paused)
- `LOW_SIGNAL`
- `NOT_A_FIT`
- `NEEDS_REVIEW_SENSITIVE`
- `BLOCKED_SUPPRESSED`
- `BLOCKED_EXISTING_RELATIONSHIP`
- `DUPLICATE`
- `RECENTLY_CONTACTED`
- `INVALID_INPUT`
- `FAILED`

**Review outcomes:** `PENDING`, `APPROVED`, `APPROVED_WITH_EDITS`, `REJECTED(reason)`

---

## 11. Evaluation plan

- **Golden set** (30 prospects to start, growing from reviewer feedback):
  - 15 normal cases.
  - 15 hard cases: moved jobs, name collisions, thin signal, only-sensitive news, stale news republished, a non-English company, a paywalled-only source, an injection test page, and no good hook (to check that the system abstains).
  - Each case is labelled by hand with the expected state, reference signals, and an acceptable-hook set that two reviewers would agree on [R: Anthropic eval guidance].
- **Fixed-rule metrics:**
  - share of quotes found verbatim;
  - share of evidence with a date, and share inside its window;
  - entity-match accuracy;
  - edge-case routing accuracy (expected state vs actual);
  - footer compliance;
  - word count;
  - cost, latency and tool calls per run.
- **Grounding metrics:**
  - draft claim precision (FActScore-style), **target 100% before the review screen**;
  - citation accuracy (FACT-style);
  - **signal recall** against the golden set, which prevents the "say less" gaming.
- **LLM judge:** pass/fail on factual accuracy, citation accuracy, offer relevance, specificity (one-field swap), non-creepiness, tone and brevity, and source quality. **Calibrated against human labels**, measuring precision and recall, not raw agreement [R: Hamel].
- **Consistency:** pass^k over 3 repeated runs per prospect, since this output reaches customers.
- **Production feedback:**
  - reviewer edit distance;
  - rejection reasons, which become new golden cases;
  - approval rate by hook type and persona;
  - later, reply and positive-reply rates and spam or unsubscribe rates.
  - Treat vendor reply-rate benchmarks only as priors.

---

## 12. Security, privacy and compliance

- **Prompt injection.**
  - Research components can't send, write to a CRM, or reach the seller's private data.
  - Outputs are schema-constrained.
  - Plan-then-execute: the recipient and allowed actions are fixed before any untrusted content is read [R].
- **Data minimisation.**
  - Collect public, professional information only.
  - No personal-life data.
  - No LinkedIn scraping (identifiers only).
- **Retention.** Evidence and page snapshots are kept for a workspace-configured time (default 90 days), then purged. Erasure by prospect is available.
- **Compliance aids** (the customer stays responsible):
  - suppression list checked at pre-flight and again at export;
  - CAN-SPAM footer fields [R: FTC];
  - optional Art. 14 notice [R: IAPP/ICO];
  - jurisdiction flags.
- **Secrets.**
  - Kept in environment variables or the platform's secret store.
  - Never logged.
  - Langfuse prompt capture is redacted for PII where required.

---

## 13. UI (what gets graded and what reps use)

1. **New run:**
   - prospect form, or CSV upload for a batch;
   - choice of seller profile;
   - effort tier;
   - a **Replay** toggle (cached responses, clearly badged as such).
2. **Live run view:**
   - stage timeline S0–S9 with status, duration and cost;
   - the research loop shown round by round: queries, URLs, signals added, rejected items with their reasons, and the reflector's gap decisions.
3. **Run detail:**
   - entity card;
   - evidence ledger table (filters: verified, category, date, source type);
   - hook scoreboard (top 3 with dimension bars and reasons, and vetoed items with the veto reason);
   - the draft with **sentence-level hover-citations** (quote, URL, date) and red highlights on unsupported sentences;
   - actions: approve, edit, swap hook, regenerate, reject with reason.
4. **Clarification inbox:** paused runs waiting for the rep to pick a candidate.
5. **Dashboard:**
   - runs by state;
   - approval rate and how much reps edit;
   - blocked or abstained runs by reason;
   - cost and time per draft compared with about 20 minutes of manual research;
   - an eval scorecard tab.
6. **Seller profile editor:** auto-draft from a URL, a versions list, and review-by reminders.

---

## 14. Build phases

**How to read this section.**
- §1–15 are the **full product design**, and they stay the target.
- We build **Phase P (Prototype v0, §16) first**. It covers the whole core workflow at full research, lead and message quality, simplifying only plumbing that doesn't affect output.
- Once Phase P is done, any time left goes into the add-back list below, in order. The product phases follow after that.

### Phase P: Prototype v0 (building now)

Scope, cuts, stack, screens, API contract and timeline: **§16**. It includes the Phase 0 spikes, minus DBOS.

**Exit criteria:**
- A deployed URL.
- Single and CSV runs work end to end with real research.
- The 4 demo edge cases reach their expected states.
- Two clean demo rehearsals.

### Add-back order after Phase P (if time is left)

Items cut from v0, ordered by value to a real user:

1. **DBOS durable workflows:** crash resume, queues with per-provider rate limits, a durable "wait for rep" pause.
2. **Quota-aware batch scheduler** with an ETA (needs 1).
3. **Langfuse tracing** and judge calibration in evals.
4. **CSV column-mapping UI.**
5. **Seller profile versioning**, with feedback suggestions to the profile owner.
6. **Auth and workspaces** (Supabase Auth, row-level security).
7. **Compliance extras:** retention purge, Art. 14 notice option, jurisdiction flags, re-check suppression at export.
8. **Ollama local fallback** for development.

### Full product phases (the original plan)

| Phase | Scope | Exit criteria |
|---|---|---|
| **0. Spikes** | Tavily vs Exa bake-off; DBOS durable workflow plus a pause for rep input; strict JSON structured outputs on Groq gpt-oss-120b and Gemini Flash-Lite; measure tokens per run against the free daily limits | Written results in the research log, with labels |
| **1. Happy path, end to end** | Seller profile + campaign (with merge validation), then S0–S9 with Standard tier, ledger, quote checks, scoring, draft, fact-check; CLI plus API | 5 real prospects produce `DRAFT_READY` with 100% of claims cited |
| **2. Edge cases** | Edge cases 7, 8, 23 and 25 (the demo set), then the rest of §8 | The golden set's hard cases route to their expected states |
| **3. UI** | Live run view, run detail with citations, review actions, dashboard | A rep can run, inspect and approve without the CLI |
| **4. Evals and observability** | Langfuse traces, eval runner, judge calibration, Replay mode | Eval report, plus a cost and latency budget per tier |
| **3b. Batch** | CSV upload and mapping, account grouping, two-pass triage, quota-aware queue, batch review queue, export | A 10-row CSV with mixed edge cases runs end to end and resumes after a forced restart |
| **5. Team-ready** | Auth and workspaces, profile auto-draft, suppression list, retention jobs | Multi-user deployment |
| **6. Integrations** | Gmail/Outlook **drafts** (a human still sends), CRM sync, learning from reviewer edits | — |

---

## 15. Sources (main ones)

**Research loop and agents:**
- Anthropic, multi-agent research system: https://www.anthropic.com/engineering/multi-agent-research-system
- Anthropic, Building effective agents: https://www.anthropic.com/engineering/building-effective-agents
- Anthropic, Context engineering: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Jina DeepSearch guide: https://jina.ai/news/a-practical-guide-to-implementing-deepsearch-deepresearch/ (code: https://github.com/jina-ai/node-DeepResearch)
- LangChain Open Deep Research: https://www.langchain.com/blog/open-deep-research (code, archived: https://github.com/langchain-ai/open_deep_research)
- Tavily research and company researcher: https://tavily.com/blog/research-en, https://tavily.com/blog/companyresearcher, https://github.com/guy-hartstein/company-research-agent
- Exa company researcher: https://github.com/exa-labs/company-researcher
- Gemini LangGraph quickstart (short-ID citations): https://github.com/google-gemini/gemini-fullstack-langgraph-quickstart
- Together open deep research (entity-attribute gap queries): https://github.com/togethercomputer/open_deep_research
- STORM / Co-STORM: https://github.com/stanford-oval/storm
- GPT Researcher: https://github.com/assafelovic/gpt-researcher
- dzhng deep-research: https://github.com/dzhng/deep-research
- LangChain company-researcher (schema-based reflection): https://github.com/langchain-ai/company-researcher
- Anthropic cookbook research prompts: https://github.com/anthropics/claude-cookbooks/tree/main/patterns/agents/prompts

**Grounding and verification:**
- FActScore: https://arxiv.org/abs/2305.14251
- SAFE: https://arxiv.org/abs/2403.18802
- RARR: https://arxiv.org/abs/2210.08726
- Chain-of-Verification: https://arxiv.org/abs/2309.11495
- DeepResearch Bench (FACT): https://arxiv.org/abs/2506.11763
- ALCE: https://arxiv.org/abs/2305.14627
- Anthropic, Reduce hallucinations: https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-hallucinations

**Reliability and security:**
- Willison, lethal trifecta: https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/
- Willison, prompt-injection design patterns: https://simonwillison.net/2025/Jun/13/prompt-injection-design-patterns/
- Hamel Husain, evals: https://hamel.dev/blog/posts/evals/

**Commercial tools:**
- 11x Deep Research, personalization and knowledge base docs: https://docs.11x.ai/alice/deep-research
- Clay agents: https://www.clay.com/blog/agent-use-cases-gtm
- Clay community thread on fabrication: https://community.clay.com/x/support/e67arxadzsof/strategies-to-improve-responses-from-claygent
- Unify research agents: https://docs.unifygtm.com/reference/plays/research-agents.md
- HubSpot prospecting agent: https://knowledge.hubspot.com/prospecting/use-the-prospecting-agent
- Amplemarket Duo: https://amplemarket.com/duo
- Artisan: https://support.artisan.co/build-messaging-for-your-campaign

**Personalization data (all vendor claims):**
- Gong Labs: https://www.gong.io/blog/4-data-backed-ways-to-increase-your-email-reply-rate-and-book-that-meeting
- Gong, executive replies: https://www.gong.io/blog/do-execs-really-reply-to-cold-email-here-s-what-the-data-says
- Hunter: https://hunter.io/the-state-of-cold-email-2025
- Instantly: https://instantly.ai/cold-email-benchmark-report-2026

**Compliance:**
- FTC CAN-SPAM guide: https://www.ftc.gov/business-guidance/resources/can-spam-act-compliance-guide-business
- ICO legitimate interests: https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/lawful-basis/legitimate-interests/when-can-we-rely-on-legitimate-interests/
- ICO B2B marketing: https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/business-to-business-marketing/
- Google sender guidelines: https://support.google.com/a/answer/14229414

**Could not verify:**
- OpenAI's deep research page returned 403.
- Lavender's primary benchmark report.
- The primary source for the "22.5% contact data decay" figure.
- Agentforce's per-email approval step.

---

## 16. Prototype v0: the 24-hour build (what we are building now)

**Purpose:** a placement-interview submission. It must **look like a professional SaaS product** and run the full core workflow live. Sections 1–15 remain the product spec. This section says what v0 builds, what it simplifies, and why.

### 16.1 Scope

**Kept exactly as specified:**
- Seller profile and campaign, with rule-based merge checks and the merged brief.
- Single prospect input, plus CSV up to about 20 rows.
- Identity check: contact moved, same-name collision.
- **Company-only input → suggested contact for the rep to confirm**. This is the lightweight lead-generation step.
- The bounded research loop (plan → read → quote-check → reflect → follow up, ≤2 follow-up rounds).
- The evidence ledger.
- Verification: quote check, dates, entity, source quality, sensitivity veto.
- Hook scoring with reasons and the top 3 hooks.
- A draft limited to verified evidence IDs, a claim-by-claim fact-check, and one rewrite.
- Human review: approve, edit, swap hook, regenerate, reject.
- Live stage view, run history and dashboard.
- The 4 demo edge cases.
- Cache and **Replay**.

**Rule for v0 cuts (12 Nov 2026):** cut only what does **not** affect the quality or quantity of research, lead finding or message generation. Every quality-affecting item is in scope.

**Restored or kept because they affect quality:**
- **All search providers:** Tavily, Exa (semantic and person-oriented search, entity `includeText` filter) and DuckDuckGo (`ddgs`, free supplement). Results are merged with reciprocal rank fusion and deduplicated.
- **All free connectors:** company site (sitemap, RSS, about, blog, press), Google News RSS, Greenhouse/Lever/Ashby job APIs, SEC EDGAR, Apple Podcasts search, YouTube (via search), GitHub (dev-tool companies).
- **Full-text fallbacks:** Tavily Extract, Exa contents (live crawl), Jina Reader for pages that need JavaScript.
- **All effort tiers:** Quick, Standard, Deep. Deep includes bounded gap sub-agents (≤8 tool calls each, ≤3 concurrent).
- **Best-of-2 drafting, double-sampled hook scoring**, and a quick model bake-off for the `judge` and `writer` roles on 5 prospects.
- **LLM consistency check** on profile + campaign, alongside the rule-based checks.
- **A third cloud provider** for capacity, so quota limits don't reduce research depth. Mistral was planned, but since October 2026 new free Mistral accounts can't activate API keys; GitHub Models (free with a GitHub token) replaces it. Mistral stays optional in the router if a key is ever added.
- **CSV two-pass triage:** Quick for all rows, Standard on the selected rows.
- **Batch sameness check** on drafts.
- **Rep notes / pasted post field.** Labelled rep-supplied evidence; partly closes the LinkedIn gap.
- **Eval script with an LLM rubric judge**, so prompts are tuned against numbers.

**New quality boosters:**
- **`htmldate` + JSON-LD/OpenGraph metadata** (`extruct`) for publish dates and organisation identity. This gives more items a reliable date, so more of them can be used.
- **Name and alias expansion** for people and companies, which improves recall.
- **Full page text stored in Postgres**, so quote checks and evidence survive page changes.
- **Multiple query phrasings** per signal category in round 0.

**Simplified because they don't affect output quality:**

| Product spec | v0 | Why there's no quality impact |
|---|---|---|
| Auth and workspaces | **Demo access code** + per-visitor rate limit; `workspace_id` fixed to `default` | Access control only |
| DBOS durable workflows | Background task + events in Postgres; cache makes re-runs cheap | Reliability only; a re-run gives the same result from the cache |
| Durable pause for clarification | Run ends `NEEDS_CLARIFICATION` → rep picks → new run with the identity pinned (cache reused) | Same outcome, different plumbing |
| Profile versioning | Merged-brief snapshot stored per run | Same audit trail |
| Ollama in production | Local development only | Render free can't run it; GitHub Models covers capacity |
| CSV column-mapping UI | Fixed template columns + validation preview | Input convenience only |
| Quota scheduler with ETA | Batch pauses with a clear "quota reached, resume" button | Same results, less automation |
| Langfuse | Own `llm_calls` table (prompt, response, tokens, latency) shown in the run view | Same debugging data |
| Compliance extras (retention, Art. 14, jurisdiction flags) | Do-not-contact list only | Legal hygiene, not content |

### 16.2 Stack (v0)

| Layer | Choice | Why |
|---|---|---|
| Frontend | **React + TypeScript + Vite**, **Tailwind**, **shadcn/ui** (Radix), **lucide** icons, **TanStack Query**, **Recharts** (via shadcn charts) | A professional SaaS look out of the box, accessible components, dark mode. Vite rather than Next.js because v0 needs no server rendering, which means one fewer server and a faster build. |
| Live updates | Server-Sent Events from FastAPI → `EventSource` in React | Live stage timeline without WebSocket complexity |
| Backend | **FastAPI** + Pydantic + SQLAlchemy | As in the product spec |
| Database | **Neon Postgres, free plan, Singapore** (used as a plain Postgres database, direct connection without the pooler); SQLite for local development via the same SQLAlchemy URL | History survives restarts. Chosen over Supabase (13 Nov 2026): Supabase's free projects pause after 7 days without use and need a manual restore, which would break the demo for late reviewers; Neon sleeps when idle and wakes on the next connection. |
| Deploy | **One Render free web service**. A multi-stage Docker build compiles the React app, and FastAPI serves it as static files. Kept awake by a free uptime pinger. | One URL, no CORS, one thing to keep running |
| AI and search | Groq + Gemini + GitHub Models (Mistral optional) behind the role router; Tavily + Exa + DuckDuckGo with rank fusion; all free connectors; trafilatura + htmldate + extruct; Jina Reader fallback | Breadth and depth of research are not reduced in v0 |

### 16.3 Screens (the graded UI)

1. **Access gate.** A clean single-field passcode screen.
2. **Setup wizard (stepper):** Seller profile → Campaign → Review the merged brief. Conflicts are shown inline, with a suggested fix.
3. **Campaign workspace.**
   - Prospects table with status pills, confidence and the last-run time.
   - "Add prospect" dialog: person and company, or company only.
   - CSV upload by drag and drop, with a downloadable template and a validation preview.
4. **Live run view.**
   - A vertical stage timeline (pending → running → done, or the exit state), with a duration per stage.
   - Research rounds appear as expandable groups: queries, sources, accepted and rejected items with reasons.
   - Evidence cards stream in as they are found.
5. **Run detail and review.**
   - Left: evidence ledger with filters.
   - Centre: the draft with **inline citation chips**; hovering shows the quote, source and date.
   - Right: hook scoreboard (bars per dimension, with reasons) and the vetoed items with their reason.
   - Sticky action bar: Approve / Edit / Swap hook / Regenerate / Reject with a reason. Keyboard shortcuts `A` `E` `S` `R` `X`.
6. **Clarification picker.** Candidate people or companies with evidence. Choosing one starts a pinned run.
7. **Dashboard.**
   - KPI tiles: runs, drafts ready, approval rate, median run time, tokens.
   - Chart of outcomes by state.
   - Recent runs table.
   - **Quota panel** showing today's usage per provider.

**Polish checklist:**
- One type scale (Inter or Geist).
- Consistent status colours.
- Skeleton loaders, empty states with guidance, toasts.
- Error states that explain what went wrong and what to do next.
- Dark mode.
- Responsive down to a laptop at 1280px.
- A visible **Replay** badge when a run uses cached answers.

### 16.4 API contract (written first, so frontend and backend are built in parallel)

```
POST /api/auth/check                 {code} → {ok}
GET/PUT /api/profile                  seller profile
GET/POST /api/campaigns ; GET/PUT /api/campaigns/{id} ; POST /api/campaigns/{id}/validate
GET/POST /api/campaigns/{id}/prospects ; POST /api/campaigns/{id}/prospects/csv
POST /api/runs {prospect_id, tier, replay?, pinned_identity?} → {run_id}
GET  /api/runs?campaign_id=&state=    history
GET  /api/runs/{id}                   full detail: brief, evidence, hooks, draft+claims, events, llm usage
GET  /api/runs/{id}/events            SSE stream of stage events
POST /api/runs/{id}/review            {action: approve|edit|swap_hook|regenerate|reject, ...}
GET  /api/dashboard                   KPIs, state counts, quota usage
GET  /api/export?campaign_id=         CSV of approved drafts
```

The frontend is built against typed mock responses generated from the Pydantic models, then switched to the live API.

### 16.5 24-hour timeline

| Hours | Backend | Frontend | Checkpoint |
|---|---|---|---|
| 0–2 | Repo, models, DB, LLM router, Tavily, smoke-test each provider | Vite + shadcn scaffold, theme, layout shell, routing | Both servers run; providers answer |
| 2–4 | API contract and mock data | — | Contract frozen |
| 4–10 | Identity check, connectors, research loop, reader, ledger, verification | Setup wizard, campaign workspace, add-prospect and CSV upload (against mocks) | Real evidence for 3 prospects; screens clickable |
| 10–14 | Scoring, drafting, fact-check, run states, SSE events | Live run view, run detail with citation chips and review actions | Full run from the CLI |
| 14–17 | Review actions, regenerate/swap, CSV batch, export, dashboard endpoint | Dashboard, clarification picker, polish states | Frontend wired to the live API |
| 17–20 | Edge cases on real prospects, Replay, company-only suggestion, access code, Docker + Render deploy | Empty, error and loading states, dark mode pass | Deployed URL; 4 edge cases reach their expected states |
| 20–22 | Full demo rehearsal ×2, fixes | Fixes | Two clean runs |
| 22–24 | Buffer, README, demo script, video | — | Submission ready |

**Effort after the quality audit:** the restored items add roughly 9–11 hours of work, so about 33 hours in total. To stay near 24 hours of wall-clock time, work runs in **parallel tracks** (backend core, connectors and search, frontend) using separate agents against the frozen API contract. Realistically: **about 24–30 hours wall-clock.**

**If time slips, cut only non-quality items, in this order:**
1. Dashboard charts (keep the KPI tiles).
2. Keyboard shortcuts.
3. CSV template download.
4. Dark-mode polish.

**Never cut:** research sources, the research loop, quote verification, scoring, best-of-2 drafting, fact-check, company-only suggestion, the live view, review.
