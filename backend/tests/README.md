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
| AI model router | `app.providers.llm_router`, including the Anthropic and local Claude Code adapters (a scripted `claude` command) | Missing fallback on rate limits; invalid JSON accepted; errors not mapped to retry or skip | Provider-specific quirks |
| API endpoints | FastAPI app via test client | Contract breaks the frontend would hit | UI rendering |
| Search fusion (added 13 Nov) | `app.providers.search.fusion.FusedSearcher` with fake providers | Bad merge/ranking, duplicate URLs, one provider sinking a search, unreadable hosts | Real result quality |
| Page extraction (added 13 Nov) | The page fetcher on saved real HTML | Boilerplate in text, missed dates, bad/oversized/blocked pages, fallback not used | Sites changing later |
| Email finder (added 13 Nov) | `app.providers.email_finder.HunterEmailFinder` against a scripted Hunter API; email finding through `run_prospect` | Wrong lookups, a claimed address used, failures sinking a run, searching when the rep gave an address, credits not counted | Hunter's real coverage |
| Model settings (added 13 Nov) | The `/api/models` endpoints with a scripted Anthropic API | Keys sent back to the browser, saving without a secret, wrong chain order, choices lost on restart, Claude Code offered on a server | Real provider behaviour |

Not tested here: the thin search adapters (Tavily, Exa, DuckDuckGo response mapping), which are
smoke-tested live, and real model quality, which was compared by hand on real prospects (free
models against Claude). An automated eval set is planned (SYSTEM_DESIGN.md §17.3).
