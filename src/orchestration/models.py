from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from config.settings import (
    AGENT_DRY_RUN,
    AGENT_ENABLE_ENRICHMENT,
    AGENT_ENABLE_EXPORT,
    AGENT_ENABLE_GRID,
    AGENT_ENABLE_PRICING,
    AGENT_ENABLE_RECLASSIFICATION,
    AGENT_ENABLE_SCANNING,
    AGENT_EXPORT_AFTER_RUN,
    AGENT_MAX_CELLS_PER_RUN,
    AGENT_MAX_ENRICHMENTS_PER_RUN,
    AGENT_MAX_PRICE_CHECKS_PER_RUN,
    AGENT_MAX_REGIONS_PER_RUN,
    AGENT_STALE_LOCK_MINUTES,
    AGENT_STALE_PROCESSING_MINUTES,
    AGENT_STOP_ON_STAGE_ERROR,
)


@dataclass(frozen=True)
class AgentConfig:
    """Configuration snapshot for one orchestration run."""

    dry_run: bool = AGENT_DRY_RUN
    region_id: int | None = None
    max_regions_per_run: int = AGENT_MAX_REGIONS_PER_RUN
    max_cells_per_run: int = AGENT_MAX_CELLS_PER_RUN
    max_enrichments_per_run: int = AGENT_MAX_ENRICHMENTS_PER_RUN
    max_price_checks_per_run: int = AGENT_MAX_PRICE_CHECKS_PER_RUN
    export_after_run: bool = AGENT_EXPORT_AFTER_RUN
    enable_grid: bool = AGENT_ENABLE_GRID
    enable_scanning: bool = AGENT_ENABLE_SCANNING
    enable_reclassification: bool = AGENT_ENABLE_RECLASSIFICATION
    enable_enrichment: bool = AGENT_ENABLE_ENRICHMENT
    enable_pricing: bool = AGENT_ENABLE_PRICING
    enable_export: bool = AGENT_ENABLE_EXPORT
    stop_on_stage_error: bool = AGENT_STOP_ON_STAGE_ERROR
    stale_lock_minutes: int = AGENT_STALE_LOCK_MINUTES
    stale_processing_minutes: int = AGENT_STALE_PROCESSING_MINUTES

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-safe configuration snapshot."""

        return asdict(self)


@dataclass
class StageResult:
    """Structured result for one orchestration stage."""

    stage: str
    status: str = "skipped"
    attempted: int = 0
    succeeded: int = 0
    skipped: int = 0
    failed: int = 0
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    next_action: str | None = None


@dataclass
class AgentRunSummary:
    """Human-readable summary of one agent orchestration run."""

    status: str
    dry_run: bool
    run_id: int | None = None
    region_id: int | None = None
    region_name: str | None = None
    stages: list[StageResult] = field(default_factory=list)
    cells_attempted: int = 0
    cells_completed: int = 0
    cells_failed: int = 0
    organizations_observed: int = 0
    salons_created: int = 0
    salons_updated: int = 0
    salons_accepted: int = 0
    salons_rejected: int = 0
    enrichments_attempted: int = 0
    enrichments_succeeded: int = 0
    price_checks_attempted: int = 0
    prices_found: int = 0
    export_path: str | None = None
    remaining_pending_cells: int = 0
    next_recommended_action: str | None = None
    blockers: list[str] = field(default_factory=list)

    def stage_names(self) -> list[str]:
        """Return executed stage names in order."""

        return [stage.stage for stage in self.stages if stage.status != "skipped"]
