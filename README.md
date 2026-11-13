# Lede

> **Try it live:** [lede-fgxl.onrender.com](https://lede-fgxl.onrender.com)<br>
> **Access code:** `zamp-lede-2026`
>
> The app starts empty: fill in the Seller profile, create a campaign, add a real prospect and choose
> **Research** (about 2 minutes). Use real companies and people; made-up names find nothing. The
> free server may take up to a minute to wake if it has been idle, and everyone with the code shares
> one workspace.

*Lede* (pronounced "leed") is the journalist's word for the opening line of a story: the line that
makes someone keep reading. This tool writes that line for sales outreach, and backs it with a
source.

Lede turns a sales prospect into a short, personalised outreach email in which **every claim is
grounded in a public source**. It confirms who the person is, researches real signals about them and
their company, checks each fact against the page it came from, picks the opener that best fits the
seller's offer, writes the email and fact-checks it sentence by sentence. A person reviews and
approves every email. **Lede never sends anything itself.**

When the evidence is weak, wrong or risky, Lede says so and stops or asks. It never invents a hook.

Built for the Zamp AI Solutions Analyst case study (problem statement 3). The full design rationale,
with sources, is in [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md).

---

## Contents

1. [What a rep does with it](#what-a-rep-does-with-it)
2. [How a run works](#how-a-run-works)
3. [How runs end](#how-runs-end)
4. [Why the output can be trusted](#why-the-output-can-be-trusted)
5. [Features](#features)
6. [Architecture](#architecture)
7. [AI models](#ai-models)
8. [Research sources](#research-sources)
9. [Run it locally](#run-it-locally)
10. [Configuration](#configuration)
11. [Deploy](#deploy)
12. [API](#api)
13. [Testing and quality](#testing-and-quality)
14. [Security and privacy](#security-and-privacy)
15. [Limitations and next steps](#limitations-and-next-steps)
16. [Development conventions](#development-conventions)

---

## What a rep does with it

1. **Describe the seller once** (Seller profile): the company, the product, the problem it solves,
   who it sells to, the product claims the email may make, the claims it must never make, the tone
   and a footer (opt-out and address, as anti-spam law requires).
2. **Create a campaign**: why you are writing to this group (objective, angle, call to action,
   which kinds of news matter most). Lede checks the campaign against the profile: a campaign can
   narrow the profile but never contradict it.
3. **Add prospects**, one at a time or from a CSV. Each needs a company; a person, title, website,
   LinkedIn URL, email and notes are optional. Leave the person blank and Lede suggests who to write
   to.
4. **Run research** (Quick, Standard or Deep) and watch it live: confirming the person, research
   rounds, checking claims, scoring openers, writing, fact-checking, finding their email.
5. **Review the draft.** Every claim is highlighted and linked to the quote and page it came from.
   Approve, edit (the edit is re-checked against the rules) or reject with a reason.
6. **Send it yourself.** Copy the email, open it in Gmail with the address, subject and body filled
   in, or find the person on LinkedIn. Or download all approved drafts as a spreadsheet.

The **Overview** shows what needs you (drafts to review, contacts to choose, runs to retry), how runs
ended, the path from research to approval, and how much of each free allowance is used this month.

---

## How a run works

```
 Prospect ──▶ Pre-flight ──▶ Confirm identity ──▶ Research loop ──▶ Verify ──▶ Score openers
 (company,    (input and      (right person at     (plan, search,     (quote on    (6 dimensions,
  person?)     brief usable)   the right company?)  read, reflect;     page, claim  2 samples each,
                    │                │              bounded rounds)    entailed)    weighted total)
                    ▼                ▼                                                   │
              INVALID_INPUT   NEEDS_CLARIFICATION / CONTACT_MOVED            LOW_SIGNAL ◀─┤
                                                                   NEEDS_REVIEW_SENSITIVE ◀┤
                                                                                         ▼
       Find email ◀── Fact-check every sentence (up to 2 revisions) ◀── Write 2 drafts, keep the better
           │                         │
           ▼                         ▼
      DRAFT_READY              DRAFT_HELD (a sentence still fails: the rep fixes it)
           │
           ▼
      Human review: approve · edit · reject   ──▶   Copy · Open in Gmail · LinkedIn · CSV export
```

| Step | What happens | Who decides |
|---|---|---|
| **Pre-flight** | Checks the input and that the campaign brief is usable. | Code |
| **Confirm identity** | Searches for the person at the company. "Confirmed" needs a source that shows them there. Several matches, a person who moved, or a name that can't be confirmed **pauses the run** and asks the rep, with suggestions of people who do work there. A company-only prospect gets suggested contacts. | AI proposes, code requires proof |
| **Research loop** | A planner writes searches for the signal types the campaign cares about; pages are fetched and read; a reader proposes facts, each with an exact quote; a reflector looks for gaps and plans the next round. Rounds, searches and pages all have hard budgets per tier. | AI, inside code-enforced budgets |
| **Verify** | Code checks every quote is really on its page (quotes that aren't are dropped). A separate checker model confirms the claim follows from its quote. Recency windows, source quality, entity match and sensitivity are applied by rules. | Code first, then AI |
| **Score openers** | The best candidates are scored 1–5 on six dimensions (fit to the offer, specificity, recency, fit to the persona, source strength, closeness to the person), twice each, and averaged. Code applies the seller's weights and the minimum bar (3.0). | AI scores, code ranks |
| **Write** | Two drafts from the top opener (with alternates as context); the better one is kept. The writer may only use facts from the ledger and approved product claims. | AI |
| **Fact-check** | A different model checks each sentence against the evidence. Unsupported sentences are revised (up to twice); anything still failing holds the draft for the rep. Draft rules (length, banned phrases, never-claims, a greeting by first name, no present-tense words on stale news) are checked by code. | AI checks, code enforces |
| **Find email** | Only when the rep gave none and a draft was written: first any address of theirs published on the pages already read, then the Hunter email finder. | Code |

Research depth:

| Tier | Rounds after the first | Searches | Pages | Openers scored |
|---|---|---|---|---|
| Quick | 0 | 8 | 10 | 6 |
| Standard | up to 2 | 20 | 25 | 12 |
| Deep | up to 4 | 40 | 50 | 20 |

---

## How runs end

Every run ends in an honest state: a draft worth sending, or a clear reason there isn't one.

| State | Meaning | What the rep sees |
|---|---|---|
| `DRAFT_READY` | Every claim is backed by evidence. | The draft with highlighted, linked claims, ready to approve. |
| `DRAFT_HELD` | A sentence still fails a check after revisions. | The draft with the failing sentence marked; edit before approving. |
| `NEEDS_CLARIFICATION` | Several people match, the name can't be confirmed, or only a company was given. | Candidates and suggestions with their sources; pick one, name someone else, or write to the name anyway. |
| `CONTACT_MOVED` | The person appears to work somewhere else now. | The evidence, and an offer to research them at the new company. |
| `LOW_SIGNAL` | Nothing specific and recent enough to personalise. | No email, and the scoreboard showing why (best opener against the 3.0 bar). |
| `NEEDS_REVIEW_SENSITIVE` | Only sensitive news was found (layoffs, lawsuits). | Not used as a hook; the rep decides. |
| `INVALID_INPUT` | The prospect or campaign needs fixing first. | What to fix. |
| `FAILED` | Every free model for a job was busy. | Research so far is kept; run it again shortly (searches are cached). |

---

## Why the output can be trusted

- **Every fact carries an exact quote, a URL and a date**, and code checks that the quote is on
  the page before the fact can be used.
- **Claims are checked twice by a model that didn't write them**: once against the quote, once
  in the finished draft.
- **The seller's own claims are fenced**: the email may only make approved product claims, and
  never-claims are blocked by rules.
- **Recency is explicit**: each signal type has a freshness window (for example 60 days for hiring,
  180 for funding), today's date is given to the writer and checker, and old news must be written
  in the past tense with its date.
- **Sensitive news is never a hook**, and personal or family details are screened out.
- **Identity needs proof**: Lede won't write to a person it can't confirm without asking first.
- **A human approves every email**, and Lede has no way to send one.
- **Good web citizen**: Lede identifies itself honestly, obeys `robots.txt` and doesn't retry a
  site that declined.

---

## Features

**Setup**
- Seller profile wizard with personas, signal priorities, approved claims, never-claims, tone, word
  limit and footer.
- Campaigns layered on the profile, with a brief check that shows where each rule came from and
  flags conflicts.

**Prospects**
- Add one by one, or import a CSV with column auto-mapping, normalised domains, duplicate detection
  and a preview of every problem before anything is saved (template included).
- Company-only prospects get suggested contacts.

**Runs**
- Live progress over server-sent events, step by step, with the facts each research round found.
- Evidence ledger with filters (about the person or the company), quotes, sources and dates.
- "Why this opener" scoreboard: every candidate's scores per dimension, with reasons.
- Draft review with highlighted claims, numbered source links, and edit, approve or reject with a
  reason. Keyboard shortcuts: A approve, E edit, X reject.

**After approval**
- "Send it yourself": the recipient address with where it came from (your list, the page it was
  published on, or Hunter with its confidence and verification status), Copy email, Open in Gmail,
  Find on LinkedIn.
- Download all approved drafts as a CSV, with the footer added, ready for a mail tool or CRM.

**Overview**
- Needs you: drafts to review, contacts to choose, runs to retry.
- Research-to-approval pipeline with conversion rates, outcome breakdown, latest activity, and free
  allowance use (Tavily, Exa, Hunter).

**Workspace**
- Campaign cards with progress; campaign page filters (All, Not run, Need you, Approved); delete a
  campaign with everything in it.
- Models page: choose your own provider and model per job, with a Test button; the free models stay
  behind as backup.
- Light and dark themes; an access code protects the whole app (optionally shown on the login page
  for a public demo).

---

## Architecture

```
 Browser (React app)
     │  same origin:  /                      built web app (served by FastAPI; Vite in development)
     │                /api/*                 JSON API, access code in the X-Access-Code header
     │                /api/runs/{id}/events  live progress (server-sent events)
     ▼
 FastAPI ── RunService (one background task per run; live event fan-out)
     │          │
     │          └── Pipeline (run_prospect)
     │                ├── Research loop ── Search fusion (Tavily, Exa, DuckDuckGo) + cache
     │                │                  ├─ Page fetcher (robots.txt, Jina fallback)
     │                │                  └─ AI roles: planner, reader, reflector
     │                ├── Identity resolver, entailment, hook scorer, writer, fact-checker
     │                ├── Policy rules: quotes, recency, sources, sensitivity, entity, draft rules
     │                └── Email finder: published addresses, then Hunter
     │
     ├── LLM router: per-job model chains, fallback on rate limits, cooldowns, corrective retry
     │               for broken JSON
     └── Store (SQLAlchemy async): SQLite locally, Postgres (Neon) deployed
            profile, campaigns, prospects, runs (outcome, events, review), settings,
            search cache, monthly spend per service
```

**Design choices**
- **Code where the logic can be specified; AI only for judgement**, and each AI role has one narrow
  job.
- **Ports and adapters**: the pipeline talks to small interfaces (`app/pipeline/ports.py`,
  `app/research/ports.py`); real adapters call models and APIs, tests plug in fakes.
- **Documents as JSON** (profile, campaigns, run outcomes), validated by Pydantic models; only
  fields that are filtered on are real columns.
- **One container, one origin**: no CORS, one deploy.

**Stack**

| Layer | Choice |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2 (async), sse-starlette, httpx |
| Extraction | trafilatura, htmldate, extruct, rank-bm25, rapidfuzz |
| Models | OpenAI-compatible endpoints (Groq, Gemini, Mistral, OpenAI, OpenRouter, Ollama), Anthropic SDK, Claude Code CLI (local only) |
| Frontend | React 19, TypeScript, Vite, Tailwind 4, shadcn/ui (Radix), TanStack Query |
| Database | SQLite (local), Postgres on Neon (deployed) |
| Hosting | Docker on Render (Singapore, free plan) |
| Tooling | uv, ruff, mypy, pytest, oxlint, Prettier, git hooks |

**Repository layout**

```
backend/                 Python 3.12+, FastAPI
  app/
    domain/              shared models: evidence, profile, campaign, prospects, run states
    policy/              deterministic rules: quotes, recency, sources, sensitivity, entity, draft rules
    context/             seller profile + campaign merged into one brief
    research/            the bounded research loop, its ports, and spotting emails on pages
    pipeline/            hook ranking and the end-to-end prospect run
    providers/           model router and adapters, search engines + rank fusion, page fetcher,
                         email finder, provider catalogue
    agents/              AI role adapters (planner, reader, reflector, resolver, judges, writer)
    services/            background runs and live events, model settings, key encryption
    api/                 HTTP API (FastAPI); also serves the built web app
    db/                  async store
    batch/               CSV import
  scripts/try_run.py     one real run from the command line
  tests/                 test-driven; agreed seams in tests/README.md
web/                     React + TypeScript (display only; all logic is in the backend)
  src/pages/             overview, campaigns, campaign workspace, run page, setup, models
  src/components/run/    stage timeline, evidence, hook scoreboard, draft review, outcome panels
Dockerfile               one image: builds the web app, serves it from the API
render.yaml              Render blueprint
SYSTEM_DESIGN.md         full design with sources
```

---

## AI models

Lede splits AI work into four jobs, each with an ordered chain of models. If a model is rate
limited, busy or returns broken JSON, the router moves to the next one and rests the failing one for
a while; a run only fails when every model for a job is unavailable.

| Job | What it does | Free default chain |
|---|---|---|
| Writing (`writer`) | Writes and revises the email. The biggest effect on quality. | Gemini 3.8 Flash → Gemini 3.7 Flash → GPT-OSS 120B (Groq) → Gemini 3.6 Flash → Qwen 3.8 27B (Groq) → Mistral Medium → Gemini 3.5 Flash → Gemini 3.5 Flash-Lite → Gemini 3.1 Flash-Lite → GPT-OSS 20B |
| Judging (`judge`) | Plans research, confirms identity, scores openers. | GPT-OSS 120B → Qwen 3.8 27B → Gemini 3.8 Flash → Gemini 3.7 Flash → Gemini 3.6 Flash → Gemini 3.5 Flash-Lite → GPT-OSS 20B → Gemini 3.1 Flash-Lite → Mistral Medium |
| Fact-checking (`checker`) | Checks claims against quotes and the draft against evidence; ideally a different family from the writer. | Qwen 3.8 27B → Gemini 3.5 Flash-Lite → Gemini 3.1 Flash-Lite → GPT-OSS 20B → GPT-OSS 120B → Gemini 3.6 Flash → Gemini 3.8 Flash → Mistral Small |
| Reading (`reader`) | Pulls facts out of every page read (the most calls). | Gemini 3.5 Flash-Lite → Gemini 3.1 Flash-Lite → GPT-OSS 20B → Qwen 3.8 27B → Mistral Small |

Free allowances are per model (for example Gemini 3.8 Flash and 3.7 Flash allow 20 requests a day
each), so spreading each job across many models multiplies the free capacity. Models without a key
in `.env` are skipped.

**Bring your own model.** On the Models page, save a key for Anthropic, OpenAI, Gemini, Groq,
OpenRouter or any OpenAI-compatible endpoint (for example a local Ollama), then choose a provider
and model per job. Your choice goes first; the free chain stays behind it as backup. Keys are
encrypted (Fernet, with a key derived from `SETTINGS_SECRET`) before they're stored and are never
sent back to the browser; only their last four characters are shown.

**Claude Code on this computer (local demos only).** With `CLAUDE_CODE_LOCAL=true`, Lede can
answer through the `claude` command and whoever is logged in to Claude Code on that machine. Each
call runs in an empty temporary folder with every tool, MCP server, skill and settings file switched
off. This option is never offered unless the setting is on, and must never be set on a server.

---

## Research sources

| Source | Used for | Free allowance |
|---|---|---|
| Tavily | Web and news search | 1,000 credits a month |
| Exa | Neural web search | $10 of credit a month |
| DuckDuckGo | Web and news search | No key needed |
| Page fetcher | Reads each page: trafilatura extraction, dates from the page, `robots.txt` respected; Jina Reader as a fallback for pages that need rendering | Jina works without a key at lower limits |
| Hunter | Finds a contact's work email when no page read shows it | 50 credits a month; charged only when an address is found |

Results from the search engines are merged by rank fusion and cached, so a re-run costs little
quota. Paid services stop being called near their monthly limit (tracked in the database), and the
free sources keep working.

---

## Run it locally

**Prerequisites:** Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 22+, and free keys for
at least one AI provider (Groq and Gemini recommended) and one search engine (Tavily recommended).

```bash
git clone <this repo> && cd lede
cp .env.example .env          # fill in keys (see Configuration)
make install                  # Python deps (uv), web deps (npm), git hooks
make check                    # backend: ruff, mypy, pytest; web: tsc, oxlint, prettier, build
```

Run it in two terminals, then open http://localhost:5173 and enter your `DEMO_ACCESS_CODE`:

```bash
make dev-api                  # FastAPI on :8000, with a local SQLite database (backend/dev.db)
make dev-web                  # Vite on :5173, proxying /api to :8000
```

Then fill in the Seller profile, create a campaign, add a prospect and choose **Research**.

One real run from the command line (uses the sample seller in `backend/samples/`):

```bash
cd backend && uv run python -m scripts.try_run --company Ramp --person "Eric Glyman" --title CEO
```

Or run the production container locally (open http://localhost:8000):

```bash
docker build -t lede . && docker run -p 8000:8000 --env-file .env lede
```

`--env-file` reads each line literally, so remove inline `# comments` from `.env` first.

---

## Configuration

All settings come from environment variables or the project-root `.env` (git-ignored). A blank
`KEY=` means "not set".

| Variable | Required | Purpose |
|---|---|---|
| `DEMO_ACCESS_CODE` | Yes | The code people type to open the app. Without it the API refuses requests. |
| `DATABASE_URL` | Deployed | Postgres connection string (`postgresql://…?sslmode=require`). Defaults to a local SQLite file. |
| `SETTINGS_SECRET` | To save model keys | Any long random string (`openssl rand -hex 32`). Changing it makes saved keys unreadable. |
| `GROQ_API_KEY` | At least one AI key | Free models on Groq. |
| `GEMINI_API_KEY` | At least one AI key | Free Gemini models. |
| `MISTRAL_API_KEY` | Optional | Extra backup models. |
| `TAVILY_API_KEY` | Recommended | Web and news search. |
| `EXA_API_KEY` | Optional | A second search engine. |
| `JINA_API_KEY` | Optional | Higher limits for the page-rendering fallback. |
| `HUNTER_API_KEY` | Optional | Email finder; shown on the dashboard when set. |
| `TAVILY_MONTHLY_CREDITS`, `EXA_MONTHLY_USD`, `HUNTER_MONTHLY_CREDITS` | Optional | Monthly limits (defaults 1000, 10 and 50). |
| `SHOW_ACCESS_CODE` | Public demos only | `true` shows the access code under the login box, for reviewers who open the link without the README. Leave unset to keep the app private. |
| `CLAUDE_CODE_LOCAL` | Local demos only | `true` offers "Claude Code on this computer" as a model. Never on a server. |
| `GITHUB_TOKEN`, `SEC_CONTACT_EMAIL` | No | Reserved for planned connectors; not used yet. |

Runs are disabled (and the app says so) until every AI job has at least one provider.

---

## Deploy

One container serves the web app and the API on the same address. The repo includes a Render
blueprint (`render.yaml`: Docker, Singapore, free plan, health check on `/api/health`) and works with
any Postgres; Neon's free tier is the tested choice.

1. **Database.** Create a Neon project (region AWS Asia Pacific, Singapore) and copy its
   connection string.
2. **Server.** In Render: **New → Blueprint**, connect GitHub, pick this repo and fill in the
   secrets it asks for: `DATABASE_URL`, `DEMO_ACCESS_CODE` and the API keys. `SETTINGS_SECRET` is
   generated for you, and `SHOW_ACCESS_CODE` is on (remove it to keep the code private). Tables are
   created on first start. Creating the service by hand instead? Add the same variables, and set
   `SETTINGS_SECRET` to the output of `openssl rand -hex 32`.
3. **Keep it awake.** Render's free plan sleeps after 15 idle minutes. An uptime monitor (for
   example UptimeRobot) calling `https://<your-app>/api/health` every 10 minutes keeps it awake.
   That endpoint never touches the database, so Neon can still pause when idle.

Every push to `main` redeploys. The deployed app has its own database, so it starts empty. Everyone
with the access code shares one workspace (one seller profile and its campaigns).

Tested before release: the image runs as a non-root user, holds no `.env` or local data, uses about
130 MB of memory (the free plan allows 512 MB), and a full run completes against Postgres.

---

## API

All routes are under `/api`. Everything except `/health`, `/auth/check` and `/auth/hint` needs the
`X-Access-Code` header. Interactive docs are at `/docs` on a running server.

| Method and path | Purpose |
|---|---|
| `GET /health` | Liveness for the uptime monitor; says whether runs are enabled. |
| `POST /auth/check` | Checks an access code. |
| `GET /auth/hint` | The access code, only when `SHOW_ACCESS_CODE` is on (for the login page); otherwise `null`. |
| `GET`, `PUT /profile` | Read or save the seller profile. |
| `GET`, `POST /campaigns` | List campaigns (with progress counts) or create one. |
| `GET`, `PUT`, `DELETE /campaigns/{id}` | Read or update a campaign, or delete it with its prospects and runs (refused while a run is going). |
| `POST /campaigns/{id}/validate` | Check the campaign against the profile; returns the merged brief and any conflicts. |
| `GET`, `POST /campaigns/{id}/prospects` | List (with each prospect's latest run) or add a prospect. |
| `POST /campaigns/{id}/prospects/csv?dry_run=` | Preview or import a CSV. |
| `POST /runs` | Start a run (`prospect_id`, `tier`, optional `pinned_identity` after a pause). |
| `GET /runs?campaign_id=&state=` | Run history. |
| `GET /runs/{id}` | A run with its outcome: identity, evidence, scores, draft, claim checks, email. |
| `GET /runs/{id}/events` | Live progress as server-sent events. |
| `POST /runs/{id}/review` | `approve`, `edit` (re-checked against the rules) or `reject` with a reason. |
| `GET /dashboard` | Outcome counts, review results, median run time, free-allowance use. |
| `GET /export?campaign_id=` | Approved drafts as CSV, footer added, with the recipient address and its source. |
| `GET /models`, `PUT`/`DELETE /models/keys/{provider}`, `PUT /models/roles`, `POST /models/test` | Model settings. |

---

## Testing and quality

- **Test-driven at agreed seams** ([backend/tests/README.md](backend/tests/README.md)): the rules
  engine, profile and campaign merge, hook ranking, research-loop control, pipeline outcomes, the
  model router, search fusion, page extraction, the email finder, model settings and the HTTP API. Only outer
  boundaries (search, models, HTTP) are faked; our own modules never are.
- **212 backend tests**, plus type checking (mypy), linting and formatting (ruff). The web app is
  type-checked (tsc), linted (oxlint), format-checked (Prettier) and built.
- **A pre-commit hook** runs the checks for the parts a commit touches, so every commit on `main`
  is green.
- **Edge cases verified on real people and companies**: a contact who moved, same-name people, a
  name that can't be confirmed, company-only prospects, and too little to say.

```bash
make check          # everything
make test           # backend tests only
```

---

## Security and privacy

- **Secrets** live only in `.env` (git-ignored) or the host's environment. The Docker image contains
  none.
- **Saved model keys** are encrypted at rest and never returned by the API.
- **The access code** is compared in constant time; the API refuses requests without it. The login
  page reveals it only when `SHOW_ACCESS_CODE` is on.
- **Prompt injection**: web pages are read by models that can only return structured facts. Nothing
  a page says can trigger an action, and every fact must match a quote that code finds on the page.
- **Claude Code** is opt-in, local only, and runs with every tool disabled in an empty folder.
- **People's data**: Lede keeps only the contact's own email address (not others found on pages),
  never uses an address its owner asked Hunter not to share, and screens personal and family details
  out of emails.
- **Sending** is always done by a person, from their own mailbox.

---

## Limitations and next steps

- **One workspace per deployment**: everyone with the access code shares one seller profile.
  Per-company accounts are the next structural step.
- **Free models write plainer drafts** than frontier models. Any user can add their own key on the
  Models page; in testing, Claude for writing and judging gave more specific, more natural emails.
- **No direct sending or CRM push**, by design for now (copy, Gmail compose link, CSV export).
- **Planned**: swap the opener and regenerate during review, an evaluation set for draft quality,
  AI usage on the dashboard, first-party connectors (SEC filings, GitHub, company news feeds) and a
  suppression list.

---

## Development conventions

- **Test-driven**: red → green, one behaviour at a time, tests only at the agreed seams.
- **Commits**: [Conventional Commits](https://www.conventionalcommits.org/) (`feat(scope): …`,
  `fix`, `test`, `docs`, `chore`, `build`, `refactor`). Each commit is one logical change with its
  tests and passes the checks for the parts it touches (enforced by the pre-commit hook).
- **Branches**: `main` is always green; work happens on `feat/*` and `fix/*` branches merged back
  fast-forward once checks pass.
- **Secrets**: only in `.env`, which is git-ignored.
