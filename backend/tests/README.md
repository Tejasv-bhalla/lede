# Test seams (agreed 12 Nov 2026)

Tests live only at these public boundaries. External services (search, AI models, HTTP) are faked
at the outer boundary; our own modules are never mocked.

| Seam | Public interface | Catches | Misses |
|---|---|---|---|
| Rules engine | `app.policy.*` (quote verification, dates/recency, sensitivity, source quality, draft rules) | Rule bugs letting an unverified, stale or sensitive fact through | AI behaviour |
| Profile + campaign merge | `app.context.merge_brief` | A campaign overwriting or loosening the profile | Meaning-level conflicts |
| Hook ranking | `app.pipeline.hooks.rank_hooks` | Vetoed items becoming hooks; wrong LOW_SIGNAL threshold | Whether AI scores are sensible |
| Research loop control | `app.research.loop.run_research` | Stop rules, budgets, dedup, dropped unverified quotes | Real search quality |
| Pipeline outcomes | `app.pipeline.run_prospect` | Wrong routing between stages / final states | Real model quality (evals) |
| AI model router | `app.providers.llm_router` | Missing fallback on rate limits; invalid JSON accepted | Provider-specific quirks |
| API endpoints | FastAPI app via test client | Contract breaks the frontend would hit | UI rendering |

Not tested here: source parsers (deferred until real responses are recorded), real model quality
(covered by `backend/evals/`).
