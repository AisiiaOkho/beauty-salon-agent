from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from config.settings import (
    ENRICHMENT_DRY_RUN,
    ENRICHMENT_MAX_ORGANIZATIONS_PER_RUN,
)
from database_manager import Database
from enrichment.organization_enricher import OrganizationEnricher


def parse_args() -> argparse.Namespace:
    """Parse enrichment command-line options."""

    parser = argparse.ArgumentParser(
        description="Run controlled 2GIS organization details enrichment."
    )
    parser.add_argument("--salon-id", type=int)
    parser.add_argument("--external-id")
    parser.add_argument("--max", type=int, default=ENRICHMENT_MAX_ORGANIZATIONS_PER_RUN)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Perform real 2GIS details requests. Defaults to dry-run.",
    )
    return parser.parse_args()


def main() -> None:
    """Initialize the database and run a controlled enrichment batch."""

    args = parse_args()
    database = Database()
    database.initialize()

    enricher = OrganizationEnricher(
        database=database,
        max_organizations_per_run=args.max,
        dry_run=ENRICHMENT_DRY_RUN and not args.live,
    )

    if args.salon_id is not None:
        summary = enricher.enrich_salon_id(args.salon_id)
    elif args.external_id:
        summary = enricher.enrich_external_id(args.external_id)
    else:
        summary = enricher.enrich_next()

    print()
    print("================================")
    print("2GIS Details Enrichment")
    print("================================")
    print(f"Dry-run: {summary.dry_run}")
    print(f"Processed: {summary.processed}")
    print(f"Succeeded: {summary.succeeded}")
    print(f"Failed: {summary.failed}")
    print(f"Skipped: {summary.skipped}")
    print(f"Contacts created: {summary.contacts_created}")
    print(f"Contacts updated: {summary.contacts_updated}")
    print(f"Contacts deactivated: {summary.contacts_deactivated}")
    print("================================")


if __name__ == "__main__":
    main()
