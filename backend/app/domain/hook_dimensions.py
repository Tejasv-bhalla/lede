"""The dimensions every candidate hook is scored on (SYSTEM_DESIGN.md §6)."""

HOOK_DIMENSIONS: tuple[str, ...] = (
    "offer_relevance",  # one honest sentence links it to a seller pain
    "specificity",  # about this person/company, fails the one-field swap
    "recency",  # how far inside its category window
    "persona_fit",  # company-level for execs, individual for ICs/managers
    "source_strength",  # primary and corroborated
    "closeness",  # the person did it > their team > the company
)

DEFAULT_HOOK_WEIGHTS: dict[str, float] = dict.fromkeys(HOOK_DIMENSIONS, 1.0)
