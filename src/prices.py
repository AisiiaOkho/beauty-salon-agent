from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from config.settings import PRICING_DRY_RUN, PRICING_MAX_SALONS_PER_RUN
from database_manager import Database
from pricing.price_extractor import PriceExtractor


def parse_args() -> argparse.Namespace:
    """Parse controlled pricing command-line options."""

    parser = argparse.ArgumentParser(
        description="Run controlled manicure price extraction."
    )
    parser.add_argument("--salon-id", type=int)
    parser.add_argument("--max", type=int, default=PRICING_MAX_SALONS_PER_RUN)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Fetch saved salon website URLs. Defaults to dry-run.",
    )
    return parser.parse_args()


def main() -> None:
    """Initialize the database and run a controlled pricing batch."""

    args = parse_args()
    database = Database()
    database.initialize()
    extractor = PriceExtractor(
        database=database,
        max_salons_per_run=args.max,
        dry_run=PRICING_DRY_RUN and not args.live,
    )

    if args.salon_id is not None:
        summary = extractor.extract_salon_id(args.salon_id)
    else:
        summary = extractor.extract_next()

    print()
    print("================================")
    print("Manicure Price Extraction")
    print("================================")
    print(f"Dry-run: {summary.dry_run}")
    print(f"Processed: {summary.processed}")
    print(f"Found: {summary.found}")
    print(f"Not found: {summary.not_found}")
    print(f"Ambiguous: {summary.ambiguous}")
    print(f"Errors: {summary.errors}")
    print(f"Skipped: {summary.skipped}")
    print("================================")


if __name__ == "__main__":
    main()
