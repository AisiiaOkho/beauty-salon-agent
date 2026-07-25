from __future__ import annotations

import uuid

from database_manager import Database

from .models import AgentConfig


class AgentLockError(RuntimeError):
    """Raised when another orchestrator owns the run lock."""


class AgentRunManager:
    """Manage run records and conservative SQLite lock ownership."""

    LOCK_NAME = "global_agent_orchestrator"

    def __init__(self, database: Database, config: AgentConfig) -> None:
        self.database = database
        self.config = config
        self.owner = str(uuid.uuid4())
        self.run_id: int | None = None
        self.lock_acquired = False

    def __enter__(self) -> "AgentRunManager":
        if self.config.dry_run:
            return self

        self.database.recover_stale_agent_runs(self.config.stale_processing_minutes)
        self.lock_acquired = self.database.acquire_agent_lock(
            lock_name=self.LOCK_NAME,
            owner=self.owner,
            stale_minutes=self.config.stale_lock_minutes,
        )

        if not self.lock_acquired:
            raise AgentLockError("Another agent run is currently active.")

        return self

    def __exit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> bool:
        if self.lock_acquired:
            self.database.release_agent_lock(self.LOCK_NAME, self.owner)

        return False

    def start_run(self, region_id: int | None) -> int | None:
        """Create a live run row, or no-op for dry-run."""

        if self.config.dry_run:
            return None

        self.run_id = self.database.create_agent_run_record(
            region_id=region_id,
            dry_run=False,
            configuration_snapshot=self.config.snapshot(),
            owner=self.owner,
        )
        return self.run_id

    def update_stage(self, stage: str) -> None:
        """Record the currently executing stage."""

        if self.run_id is None:
            return

        self.database.update_agent_run_record(
            self.run_id,
            current_stage=stage,
        )

    def finish(self, status: str, **metrics: object) -> None:
        """Finish the live run row if one exists."""

        if self.run_id is None:
            return

        self.database.finish_agent_run_record(
            self.run_id,
            status=status,
            **metrics,
        )
