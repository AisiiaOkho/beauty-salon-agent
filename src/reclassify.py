from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from config.settings import (
    RECLASSIFICATION_DRY_RUN,
    RECLASSIFICATION_MAX_RECORDS_PER_RUN,
)
from database_manager import Database
from maintenance.reclassify_salons import SalonReclassifier


def parse_args() -> argparse.Namespace:
    """Parse controlled reclassification options."""

    parser = argparse.ArgumentParser(
        description="Backfill current salon classifier state."
    )
    parser.add_argument("--salon-id", type=int)
    parser.add_argument(
        "--max",
        type=int,
        default=RECLASSIFICATION_MAX_RECORDS_PER_RUN,
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist classification state. Defaults to dry-run.",
    )
    return parser.parse_args()


def main() -> None:
    """Run the controlled classifier backfill."""

    args = parse_args()
    database = Database()
    database.initialize()
    reclassifier = SalonReclassifier(
        database=database,
        max_records_per_run=args.max,
        dry_run=RECLASSIFICATION_DRY_RUN and not args.apply,
    )
    summary = reclassifier.reclassify(salon_id=args.salon_id)

    print()
    print("================================")
    print("Salon Reclassification")
    print("================================")
    print(f"Dry-run: {summary.dry_run}")
    print(f"Processed: {summary.processed}")
    print(f"Accepted: {summary.accepted}")
    print(f"Rejected: {summary.rejected}")
    print(f"Changed: {summary.changed}")
    print(f"Unreliable: {summary.unreliable}")

    for change in summary.changes:
        if change.changed or not change.reliable:
            print(
                "Change: "
                f"id={change.salon_id} "
                f"name={change.name} "
                f"{change.previous_status}->{change.new_status} "
                f"profile={change.new_business_profile} "
                f"reason={change.rejection_reason} "
                f"reliable={change.reliable}"
            )

    print("================================")


if __name__ == "__main__":
    main()
