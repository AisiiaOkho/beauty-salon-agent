from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from config.settings import AGENT_DRY_RUN
from database_manager import Database
from orchestration.models import AgentConfig
from orchestration.pipeline import AgentPipeline


def parse_args() -> argparse.Namespace:
    """Parse global agent orchestration options."""

    parser = argparse.ArgumentParser(
        description="Run the safe resumable Beauty Salon Agent orchestrator."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--live", action="store_true")
    parser.add_argument("--region-id", type=int)
    parser.add_argument(
        "--cell-ids",
        help="Comma-separated ordered grid cell id allowlist for controlled pilots.",
    )
    parser.add_argument("--max-cells", type=int)
    parser.add_argument("--max-enrichments", type=int)
    parser.add_argument("--max-price-checks", type=int)
    parser.add_argument("--disable-grid", action="store_true")
    parser.add_argument("--enable-scanning", action="store_true")
    parser.add_argument("--disable-scanning", action="store_true")
    parser.add_argument("--enable-reclassification", action="store_true")
    parser.add_argument("--disable-reclassification", action="store_true")
    parser.add_argument("--enable-enrichment", action="store_true")
    parser.add_argument("--disable-enrichment", action="store_true")
    parser.add_argument("--enable-pricing", action="store_true")
    parser.add_argument("--disable-pricing", action="store_true")
    parser.add_argument("--enable-export", action="store_true")
    parser.add_argument("--disable-export", action="store_true")
    parser.add_argument("--continue-on-stage-error", action="store_true")
    return parser.parse_args()


def config_from_args(args: argparse.Namespace) -> AgentConfig:
    """Build an AgentConfig from settings plus explicit CLI overrides."""

    dry_run = AGENT_DRY_RUN

    if args.live:
        dry_run = False
    elif args.dry_run:
        dry_run = True

    target_cell_ids = None

    if args.cell_ids:
        target_cell_ids = [
            int(value.strip())
            for value in args.cell_ids.split(",")
            if value.strip()
        ]

    config = AgentConfig(
        dry_run=dry_run,
        region_id=args.region_id,
        target_cell_ids=target_cell_ids,
    )
    values = config.snapshot()

    if args.max_cells is not None:
        values["max_cells_per_run"] = args.max_cells

    if args.max_enrichments is not None:
        values["max_enrichments_per_run"] = args.max_enrichments

    if args.max_price_checks is not None:
        values["max_price_checks_per_run"] = args.max_price_checks

    if args.disable_grid:
        values["enable_grid"] = False

    if args.enable_scanning:
        values["enable_scanning"] = True

    if args.disable_scanning:
        values["enable_scanning"] = False

    if args.enable_reclassification:
        values["enable_reclassification"] = True

    if args.disable_reclassification:
        values["enable_reclassification"] = False

    if args.enable_enrichment:
        values["enable_enrichment"] = True

    if args.disable_enrichment:
        values["enable_enrichment"] = False

    if args.enable_pricing:
        values["enable_pricing"] = True

    if args.disable_pricing:
        values["enable_pricing"] = False

    if args.enable_export:
        values["enable_export"] = True

    if args.disable_export:
        values["enable_export"] = False

    if args.continue_on_stage_error:
        values["stop_on_stage_error"] = False

    return AgentConfig(**values)


def main() -> None:
    """Run the global agent orchestrator."""

    args = parse_args()
    config = config_from_args(args)
    database = Database()

    if not config.dry_run:
        database.initialize()

    summary = AgentPipeline(database, config).run()

    print()
    print("================================")
    print("Agent Run Summary")
    print("================================")
    print(f"Status: {summary.status}")
    print(f"Dry-run: {summary.dry_run}")
    print(f"Run ID: {summary.run_id}")
    print(f"Region: {summary.region_name} ({summary.region_id})")
    print(f"Stages executed: {', '.join(summary.stage_names())}")
    print(f"Cells attempted: {summary.cells_attempted}")
    print(f"Cells completed: {summary.cells_completed}")
    print(f"Cells failed: {summary.cells_failed}")
    print(f"Organizations observed: {summary.organizations_observed}")
    print(f"Salons created: {summary.salons_created}")
    print(f"Salons updated: {summary.salons_updated}")
    print(f"Salons accepted: {summary.salons_accepted}")
    print(f"Salons rejected: {summary.salons_rejected}")
    print(f"Enrichments attempted: {summary.enrichments_attempted}")
    print(f"Enrichments succeeded: {summary.enrichments_succeeded}")
    print(f"Price checks attempted: {summary.price_checks_attempted}")
    print(f"Prices found: {summary.prices_found}")
    print(f"Export path: {summary.export_path}")
    print(f"Remaining pending cells: {summary.remaining_pending_cells}")
    print(f"Next action: {summary.next_recommended_action}")

    if summary.blockers:
        print(f"Blockers: {'; '.join(summary.blockers)}")

    print("================================")


if __name__ == "__main__":
    main()
