from typing import Any

from database_manager import Database


class RegionManager:
    """
    Выбирает регион и управляет его статусом.
    """

    def __init__(self, database: Database) -> None:
        self.database = database

    def get_next_region(self) -> dict[str, Any] | None:
        return self.database.get_next_region()

    def start_next_region(self) -> dict[str, Any] | None:
        region = self.get_next_region()

        if region is None:
            return None

        if region["status"] == "pending":
            self.database.mark_region_in_progress(
                region["id"]
            )

            region = self.database.get_region_progress(
                region["id"]
            )

        return region

    def complete_region(
        self,
        region_id: int,
        comment: str | None = None,
    ) -> None:
        self.database.mark_region_completed(
            region_id=region_id,
            comment=comment,
        )
        