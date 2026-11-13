"""Build the real pipeline: shared clients and quota state, fresh role adapters per run."""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import httpx2

from app.agents.identity import SearchResolver
from app.agents.judging import LLMEntailment, LLMFactChecker, LLMScorer
from app.agents.research import LLMPlanner, LLMReader, LLMReflector
from app.agents.writing import LLMWriter
from app.config import Settings
from app.domain.models import Tier
from app.pipeline.run import PipelineDeps
from app.providers.email_finder import HunterEmailFinder
from app.providers.fetch import PageFetcher
from app.providers.llm_roles import build_routes
from app.providers.llm_router import LLMRouter
from app.providers.search.engines import DuckDuckGoEngine, ExaEngine, TavilyEngine
from app.providers.search.fusion import EngineBudget, FusedSearcher, SearchLedger, SearchProvider
from app.research.loop import ResearchDeps


@dataclass(slots=True)
class Runtime:
    """Long-lived pieces shared by every run: HTTP pools, the model router (and its rate-limit
    cooldowns), the search engines and their budgets."""

    settings: Settings
    router: LLMRouter
    http: httpx.AsyncClient
    llm_http: httpx2.AsyncClient
    engines: dict[str, SearchProvider]
    budgets: dict[str, EngineBudget]
    ledger: SearchLedger

    @classmethod
    def create(cls, settings: Settings, ledger: SearchLedger) -> Runtime:
        llm_http = httpx2.AsyncClient(timeout=60.0)
        engines: dict[str, SearchProvider] = {"ddg": DuckDuckGoEngine()}
        budgets: dict[str, EngineBudget] = {}
        if settings.tavily_api_key:
            engines["tavily"] = TavilyEngine(settings.tavily_api_key.get_secret_value())
            budgets["tavily"] = EngineBudget(settings.tavily_monthly_credits, 1.0)
        if settings.exa_api_key:
            engines["exa"] = ExaEngine(settings.exa_api_key.get_secret_value())
            budgets["exa"] = EngineBudget(settings.exa_monthly_usd, settings.exa_usd_per_search)
        return cls(
            settings=settings,
            router=LLMRouter(build_routes(settings), http_client=llm_http),
            http=httpx.AsyncClient(),
            llm_http=llm_http,
            engines=engines,
            budgets=budgets,
            ledger=ledger,
        )

    @property
    def ready(self) -> bool:
        return all(self.router.has_role(r) for r in ("judge", "writer", "reader", "checker"))

    def searcher(self, tier: Tier) -> FusedSearcher:
        # Quick runs use the free engine plus one paid engine; deeper runs use every engine.
        names = ["ddg", "tavily"] if tier is Tier.QUICK else list(self.engines)
        return FusedSearcher(
            [self.engines[n] for n in names if n in self.engines],
            ledger=self.ledger,
            budgets=self.budgets,
        )

    def deps(self, tier: Tier) -> PipelineDeps:
        searcher = self.searcher(tier)
        jina = self.settings.jina_api_key
        return PipelineDeps(
            research=ResearchDeps(
                searcher=searcher,
                fetcher=PageFetcher(
                    self.http,
                    user_agent=self.settings.user_agent,
                    jina_api_key=jina.get_secret_value() if jina else None,
                ),
                planner=LLMPlanner(self.router),
                reader=LLMReader(self.router),
                reflector=LLMReflector(self.router),
            ),
            resolver=SearchResolver(self.router, searcher),
            entailment=LLMEntailment(self.router),
            scorer=LLMScorer(self.router),
            writer=LLMWriter(self.router),
            fact_checker=LLMFactChecker(self.router),
            email_finder=self.email_finder(),
        )

    def email_finder(self) -> HunterEmailFinder | None:
        key = self.settings.hunter_api_key
        return HunterEmailFinder(self.http, key.get_secret_value()) if key else None

    async def close(self) -> None:
        await self.http.aclose()
        await self.llm_http.aclose()
