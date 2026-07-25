from __future__ import annotations

from collections.abc import Callable

from database_manager import Database
from enrichment.organization_enricher import OrganizationEnricher
from exporting.excel_exporter import ExcelExporter
from maintenance.reclassify_salons import SalonReclassifier
from pricing.price_extractor import PriceExtractor
from scanner.grid_manager import GridManager
from scanner.salon_scanner import SalonScannerManager

from .models import AgentConfig, AgentRunSummary, StageResult
from .run_manager import AgentLockError, AgentRunManager

ProgressLogger = Callable[[str], None]


class AgentPipeline:
    """Coordinate existing modules into one resumable agent run."""

    def __init__(
        self,
        database: Database,
        config: AgentConfig,
        progress_logger: ProgressLogger | None = None,
    ) -> None:
        self.database = database
        self.config = config
        self.progress_logger = progress_logger or print

    def run(self) -> AgentRunSummary:
        """Execute a dry-run preview or one controlled live orchestration run."""

        if self.config.dry_run:
            return self._dry_run()

        summary = AgentRunSummary(status="running", dry_run=False)

        try:
            with AgentRunManager(self.database, self.config) as run_manager:
                region = self.database.claim_region_for_agent(self.config.region_id)

                if region is None:
                    summary.status = "complete"
                    summary.next_recommended_action = "No unfinished region found."
                    return summary

                summary.region_id = int(region["id"])
                summary.region_name = str(region["name"])
                run_id = run_manager.start_run(summary.region_id)
                summary.run_id = run_id
                try:
                    self._execute_live(region, summary, run_manager)
                except KeyboardInterrupt:
                    summary.status = "paused"
                    summary.blockers.append("Interrupted by user.")
                    run_manager.finish("paused", **self._run_metrics(summary))
                    return summary
                except Exception as error:
                    summary.status = "failed"
                    summary.blockers.append(str(error))
                    run_manager.finish("failed", **self._run_metrics(summary))
                    return summary

                run_manager.finish(summary.status, **self._run_metrics(summary))
        except AgentLockError as error:
            summary.status = "blocked"
            summary.blockers.append(str(error))
        except KeyboardInterrupt:
            summary.status = "paused"
            summary.blockers.append("Interrupted by user.")

        return summary

    def _dry_run(self) -> AgentRunSummary:
        region = self.database.peek_next_region(self.config.region_id)
        summary = AgentRunSummary(status="dry_run", dry_run=True)

        if region is None:
            summary.next_recommended_action = "No unfinished region found."
            return summary

        region_id = int(region["id"])
        generation = self.database.get_grid_generation(region_id)
        next_cell = (
            self.database.get_next_pending_cell_preview_from_ids(
                region_id,
                self.config.target_cell_ids,
            )
            if self.config.target_cell_ids
            else self.database.get_next_pending_cell_preview(region_id)
        )
        cell_counts = self.database.get_region_cell_status_counts(region_id)
        pending_for_run = (
            self._pending_target_cell_count(region_id)
            if self.config.target_cell_ids
            else cell_counts.get("pending", 0)
        )
        summary.region_id = region_id
        summary.region_name = str(region["name"])
        summary.remaining_pending_cells = cell_counts.get("pending", 0)
        summary.stages.extend(
            [
                StageResult(
                    "select_region",
                    status="would_run",
                    metrics={"region_id": region_id, "region_name": region["name"]},
                ),
                StageResult(
                    "ensure_grid",
                    status="would_skip" if generation and generation["status"] == "complete" else "would_run",
                    metrics={"grid_status": generation["status"] if generation else None},
                ),
                StageResult(
                    "scan_cells",
                    status="would_run" if self.config.enable_scanning and next_cell else "would_skip",
                    attempted=min(self.config.max_cells_per_run, pending_for_run),
                    metrics={
                        "next_cell_id": next_cell["id"] if next_cell else None,
                        "next_cell_order": next_cell["cell_order"] if next_cell else None,
                    },
                ),
                StageResult(
                    "reclassify",
                    status="would_run" if self.config.enable_reclassification else "would_skip",
                ),
                StageResult(
                    "enrich_details",
                    status="would_run" if self.config.enable_enrichment else "would_skip",
                    attempted=self.config.max_enrichments_per_run,
                ),
                StageResult(
                    "check_prices",
                    status="would_run" if self.config.enable_pricing else "would_skip",
                    attempted=self.config.max_price_checks_per_run,
                ),
                StageResult(
                    "export_results",
                    status="would_run" if self.config.enable_export else "would_skip",
                    metrics={"output_dir": "exports"},
                ),
            ]
        )
        summary.next_recommended_action = "Run with --live to mutate state."
        return summary

    def _execute_live(
        self,
        region: dict[str, object],
        summary: AgentRunSummary,
        run_manager: AgentRunManager,
    ) -> None:
        summary.status = "complete"
        self._run_stage("select_region", summary, run_manager, lambda: StageResult(
            "select_region",
            status="complete",
            succeeded=1,
            metrics={"region_id": region["id"], "region_name": region["name"]},
        ))

        if self.config.enable_grid:
            self._run_stage("ensure_grid", summary, run_manager, lambda: self._ensure_grid(region))

        if self.config.enable_scanning:
            self._run_stage("scan_cells", summary, run_manager, lambda: self._scan_cells(region, summary))

        if self.config.enable_reclassification:
            self._run_stage("reclassify", summary, run_manager, self._reclassify_missing)

        if self.config.enable_enrichment:
            self._run_stage("enrich_details", summary, run_manager, lambda: self._enrich(summary))

        if self.config.enable_pricing:
            self._run_stage("check_prices", summary, run_manager, lambda: self._price(summary))

        if self.config.enable_export or self.config.export_after_run:
            self._run_stage("export_results", summary, run_manager, lambda: self._export(region, summary))

        self._run_stage("complete_region", summary, run_manager, lambda: self._complete_region(region, summary))
        counts = self.database.get_region_cell_status_counts(int(region["id"]))
        summary.remaining_pending_cells = counts.get("pending", 0)

        if summary.remaining_pending_cells > 0:
            summary.next_recommended_action = "Run again to process the next pending cell."
        else:
            summary.next_recommended_action = "No pending cells remain for this region."

    def _run_stage(
        self,
        stage: str,
        summary: AgentRunSummary,
        run_manager: AgentRunManager,
        callback: Callable[[], StageResult],
    ) -> None:
        try:
            run_manager.update_stage(stage)
            result = callback()
        except Exception as error:
            result = StageResult(
                stage=stage,
                status="failed",
                failed=1,
                warnings=[str(error)],
            )
            summary.stages.append(result)
            summary.status = "failed"

            if run_manager.run_id is not None:
                self.database.update_agent_run_record(
                    run_manager.run_id,
                    status="failed",
                    error_stage=stage,
                    error_message=str(error),
                )

            if self.config.stop_on_stage_error:
                raise

            return

        summary.stages.append(result)

        if result.status == "failed":
            summary.status = "failed"

            if run_manager.run_id is not None:
                self.database.update_agent_run_record(
                    run_manager.run_id,
                    status="failed",
                    error_stage=stage,
                    error_message="Stage returned failed status.",
                )

            if self.config.stop_on_stage_error:
                raise RuntimeError(f"Stage failed: {stage}")

    def _ensure_grid(self, region: dict[str, object]) -> StageResult:
        result = GridManager(self.database).ensure_grid_for_region(region)
        return StageResult(
            "ensure_grid",
            status="complete",
            attempted=1,
            succeeded=1,
            metrics={"created": result.created, "cells_count": result.cells_count},
        )

    def _scan_cells(
        self,
        region: dict[str, object],
        summary: AgentRunSummary,
    ) -> StageResult:
        region_id = int(region["id"])
        before_counts = self.database.get_region_cell_status_counts(region_id)
        scanner = SalonScannerManager(
            self.database,
            max_cells_per_run=self.config.max_cells_per_run,
            dry_run=False,
            target_cell_ids=self.config.target_cell_ids,
            progress_logger=self.progress_logger,
        )
        scan_summary = scanner.scan_region(region)
        after_counts = self.database.get_region_cell_status_counts(region_id)
        summary.cells_attempted += scan_summary.cells_processed
        summary.cells_completed += max(
            0,
            after_counts.get("completed", 0) - before_counts.get("completed", 0),
        )
        summary.cells_failed += scan_summary.errors
        summary.organizations_observed += scan_summary.raw_organizations_found
        summary.salons_accepted += scan_summary.accepted_salons
        summary.salons_rejected += scan_summary.rejected_results
        summary.salons_updated += scan_summary.duplicates_merged
        summary.salons_created += max(
            0,
            scan_summary.accepted_salons - scan_summary.duplicates_merged,
        )
        return StageResult(
            "scan_cells",
            status="complete" if scan_summary.errors == 0 else "failed",
            attempted=scan_summary.cells_processed,
            succeeded=scan_summary.cells_processed - scan_summary.errors,
            failed=scan_summary.errors,
            metrics={
                "raw_organizations_found": scan_summary.raw_organizations_found,
                "accepted_salons": scan_summary.accepted_salons,
                "rejected_results": scan_summary.rejected_results,
                "duplicates_merged": scan_summary.duplicates_merged,
            },
        )

    def _reclassify_missing(self) -> StageResult:
        reclassifier = SalonReclassifier(
            self.database,
            max_records_per_run=100,
            dry_run=False,
        )
        result = reclassifier.reclassify(only_missing_current_version=True)
        return StageResult(
            "reclassify",
            status="complete",
            attempted=result.processed,
            succeeded=result.processed,
            metrics={
                "changed": result.changed,
                "accepted": result.accepted,
                "rejected": result.rejected,
                "unreliable": result.unreliable,
            },
        )

    def _enrich(self, summary: AgentRunSummary) -> StageResult:
        enricher = OrganizationEnricher(
            self.database,
            max_organizations_per_run=self.config.max_enrichments_per_run,
            dry_run=False,
            progress_logger=self.progress_logger,
        )
        result = enricher.enrich_next()
        summary.enrichments_attempted += result.processed
        summary.enrichments_succeeded += result.succeeded
        return StageResult(
            "enrich_details",
            status="complete" if result.failed == 0 else "failed",
            attempted=result.processed,
            succeeded=result.succeeded,
            failed=result.failed,
            skipped=result.skipped,
        )

    def _price(self, summary: AgentRunSummary) -> StageResult:
        eligible = self.database.count_pricing_eligible_salons()

        if eligible == 0:
            return StageResult(
                "check_prices",
                status="skipped",
                skipped=1,
                warnings=["No accepted salon has an attributable pricing source."],
            )

        extractor = PriceExtractor(
            self.database,
            max_salons_per_run=self.config.max_price_checks_per_run,
            dry_run=False,
            progress_logger=self.progress_logger,
        )
        result = extractor.extract_next()
        summary.price_checks_attempted += result.processed
        summary.prices_found += result.found
        return StageResult(
            "check_prices",
            status="complete" if result.errors == 0 else "failed",
            attempted=result.processed,
            succeeded=result.found,
            failed=result.errors,
            skipped=result.skipped,
            metrics={"not_found": result.not_found, "ambiguous": result.ambiguous},
        )

    def _export(
        self,
        region: dict[str, object],
        summary: AgentRunSummary,
    ) -> StageResult:
        result = ExcelExporter(
            self.database,
            dry_run=False,
        ).export(region_id=int(region["id"]))
        summary.export_path = result.output_path
        return StageResult(
            "export_results",
            status="complete",
            attempted=1,
            succeeded=1,
            metrics={
                "output_path": result.output_path,
                "accepted_count": result.accepted_count,
                "rejected_count": result.rejected_count,
            },
        )

    def _complete_region(
        self,
        region: dict[str, object],
        summary: AgentRunSummary,
    ) -> StageResult:
        completed = self.database.complete_region_if_terminal(int(region["id"]))
        status = "complete" if completed else "skipped"
        return StageResult(
            "complete_region",
            status=status,
            attempted=1,
            succeeded=1 if completed else 0,
            skipped=0 if completed else 1,
        )

    def _run_metrics(self, summary: AgentRunSummary) -> dict[str, object]:
        return {
            "cells_attempted": summary.cells_attempted,
            "cells_completed": summary.cells_completed,
            "cells_failed": summary.cells_failed,
            "organizations_observed": summary.organizations_observed,
            "salons_created": summary.salons_created,
            "salons_updated": summary.salons_updated,
            "salons_accepted": summary.salons_accepted,
            "salons_rejected": summary.salons_rejected,
            "enrichments_attempted": summary.enrichments_attempted,
            "enrichments_succeeded": summary.enrichments_succeeded,
            "price_checks_attempted": summary.price_checks_attempted,
            "prices_found": summary.prices_found,
            "export_path": summary.export_path,
        }

    def _pending_target_cell_count(self, region_id: int) -> int:
        if not self.config.target_cell_ids:
            return 0

        placeholders = ",".join("?" for _ in self.config.target_cell_ids)

        with self.database.connect() as connection:
            row = connection.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM grid_cells
                WHERE region_id = ?
                  AND status = 'pending'
                  AND id IN ({placeholders})
                """,
                [region_id, *self.config.target_cell_ids],
            ).fetchone()

        return int(row["total"])
