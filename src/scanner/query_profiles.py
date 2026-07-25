from __future__ import annotations

from dataclasses import dataclass

from config.settings import DEFAULT_QUERY_PROFILE, QUERY_PROFILES


@dataclass(frozen=True)
class QueryProfile:
    """Named immutable search-query profile."""

    name: str
    queries: tuple[str, ...]


def resolve_query_profile(
    profile_name: str | None = None,
    explicit_queries: list[str] | tuple[str, ...] | None = None,
) -> QueryProfile:
    """Resolve a scanner query profile or explicit query list."""

    if explicit_queries is not None:
        queries = tuple(query for query in explicit_queries if query.strip())

        if not queries:
            raise ValueError("Explicit query list cannot be empty.")

        return QueryProfile(name=profile_name or "explicit", queries=queries)

    selected = profile_name or DEFAULT_QUERY_PROFILE

    if selected not in QUERY_PROFILES:
        raise ValueError(f"Unknown query profile: {selected}")

    return QueryProfile(name=selected, queries=tuple(QUERY_PROFILES[selected]))
