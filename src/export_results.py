from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from config.settings import EXPORT_DRY_RUN, EXPORT_INCLUDE_REJECTED, EXPORT_OUTPUT_DIR
from database_manager import Database
from exporting.excel_exporter import ExcelExporter


def parse_args() -> argparse.Namespace:
    """Parse controlled Excel export options."""

    parser = argparse.ArgumentParser(
        description="Export accepted salon results to Excel."
    )
    parser.add_argument("--region-id", type=int)
    parser.add_argument("--output")
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the workbook. Defaults to dry-run.",
    )
    parser.add_argument(
        "--no-rejected",
        action="store_true",
        help="Omit the rejected audit sheet.",
    )
    parser.add_argument(
        "--output-dir",
        default=EXPORT_OUTPUT_DIR,
    )
    return parser.parse_args()


def main() -> None:
    """Run a dry-run preview or write one Excel workbook."""

    args = parse_args()
    database = Database()
    database.initialize()
    exporter = ExcelExporter(
        database=database,
        output_dir=args.output_dir,
        include_rejected=EXPORT_INCLUDE_REJECTED and not args.no_rejected,
        dry_run=EXPORT_DRY_RUN and not args.write,
    )
    result = exporter.export(
        output_path=args.output,
        region_id=args.region_id,
    )

    print()
    print("================================")
    print("Excel Export")
    print("================================")
    print(f"Dry-run: {not result.file_written}")
    print(f"Output: {result.output_path}")
    print(f"Accepted rows: {result.accepted_count}")
    print(f"Rejected rows: {result.rejected_count}")

    if result.file_written:
        print(f"File size: {result.file_size_bytes} bytes")

    print("================================")


if __name__ == "__main__":
    main()
