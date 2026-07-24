from database_manager import Database
from scanner.grid_manager import GridManager
from scanner.region_manager import RegionManager
from scanner.salon_scanner import SalonScannerManager


def main() -> None:
    print("🤖 Запуск Beauty Salon Agent...")

    database = Database()
    database.initialize()

    region_manager = RegionManager(database)
    region = region_manager.start_next_region()

    if region is None:
        print("🎉 Все регионы уже обработаны.")
        return

    print()
    print("================================")
    print("Следующий регион для обработки")
    print("================================")
    print(f"Порядковый номер: {region['scan_order']}")
    print(f"Регион: {region['name']}")
    print(f"Статус: {region['status']}")
    print("================================")

    grid_manager = GridManager(database)
    grid_result = grid_manager.ensure_grid_for_region(region)

    print()
    print("================================")
    print("Сетка региона")
    print("================================")

    if grid_result.created:
        print(f"✅ Сетка создана: {grid_result.cells_count} ячеек.")
    else:
        print(
            "ℹ️ Сетка уже существует: "
            f"{grid_result.cells_count} ячеек."
        )

    print("================================")

    scanner_manager = SalonScannerManager(database)
    scan_summary = scanner_manager.scan_region(region)

    print()
    print("================================")
    print("Сканирование 2GIS")
    print("================================")
    print(f"Режим dry-run: {scan_summary.dry_run}")
    print(f"Обработано ячеек: {scan_summary.cells_processed}")
    print(
        "Найдено raw организаций: "
        f"{scan_summary.raw_organizations_found}"
    )
    print(f"Принято салонов: {scan_summary.accepted_salons}")
    print(f"Отклонено результатов: {scan_summary.rejected_results}")
    print(f"Дубликатов объединено: {scan_summary.duplicates_merged}")
    print(f"Ошибок: {scan_summary.errors}")
    print("================================")


if __name__ == "__main__":
    main()
