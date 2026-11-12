# Signal to Draft

Turns a sales prospect into an evidence-grounded, personalised outreach draft. The system researches
real public signals, checks every fact against its source, picks the hook that best fits the
campaign, writes a short email and fact-checks it. A human approves every message; nothing is sent
automatically.

Built for the AI Solutions Analyst case study (PS-3). Design: [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md).

## Repository layout

```
backend/        Python 3.12+ · FastAPI · pipeline, research loop, rules
  app/
    domain/     shared models (evidence, profile, campaign, run states)
    policy/     deterministic rules: quotes, recency, sources, sensitivity, entity, draft rules
    context/    seller profile + campaign merge
    research/   bounded research loop and its ports (search, fetch, AI roles)
    pipeline/   hook ranking and the end-to-end prospect run
  tests/        test-driven; seams listed in tests/README.md
web/            React + TypeScript + Vite + shadcn/ui (display only)
```

## Getting started

```bash
cp .env.example .env          # fill in the free-tier keys
make install                  # Python deps via uv, git hooks
make check                    # lint + type-check + tests
```

## Development conventions

- **Test-driven:** red → green, one behaviour at a time, tests only at the agreed seams.
- **Commits:** [Conventional Commits](https://www.conventionalcommits.org/) (`feat(scope): …`,
  `fix`, `test`, `docs`, `chore`, `refactor`). Each commit is one logical change with its tests and
  passes `make check` (enforced by the pre-commit hook).
- **Branches:** `main` is always green; work happens on `feat/*` / `fix/*` branches merged back
  fast-forward once checks pass.
- **Secrets:** only in `.env`, which is git-ignored.
