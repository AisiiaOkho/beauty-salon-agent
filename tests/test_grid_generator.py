from __future__ import annotations

import unittest

from shapely.geometry import MultiPolygon, Polygon

from geometry.grid_generator import ProjectedGridGenerator


class ProjectedGridGeneratorTests(unittest.TestCase):
    def test_polygon_with_hole_excludes_hole_cells(self) -> None:
        boundary = Polygon(
            shell=[
                (30.0, 55.0),
                (30.12, 55.0),
                (30.12, 55.12),
                (30.0, 55.12),
                (30.0, 55.0),
            ],
            holes=[
                [
                    (30.04, 55.04),
                    (30.08, 55.04),
                    (30.08, 55.08),
                    (30.04, 55.08),
                    (30.04, 55.04),
                ]
            ],
        )
        solid_boundary = Polygon(boundary.exterior)
        generator = ProjectedGridGenerator(cell_size_meters=1000)

        cells = list(generator.iter_cells(MultiPolygon([boundary])))
        solid_cells = list(generator.iter_cells(MultiPolygon([solid_boundary])))

        self.assertGreater(len(cells), 0)
        self.assertLess(len(cells), len(solid_cells))

    def test_multipolygon_islands_are_kept(self) -> None:
        first = Polygon(
            [
                (30.0, 55.0),
                (30.02, 55.0),
                (30.02, 55.02),
                (30.0, 55.02),
                (30.0, 55.0),
            ]
        )
        second = Polygon(
            [
                (31.0, 55.0),
                (31.02, 55.0),
                (31.02, 55.02),
                (31.0, 55.02),
                (31.0, 55.0),
            ]
        )
        generator = ProjectedGridGenerator(cell_size_meters=1000)

        cells = list(generator.iter_cells(MultiPolygon([first, second])))

        self.assertTrue(any(cell.center_lon < 30.5 for cell in cells))
        self.assertTrue(any(cell.center_lon > 30.5 for cell in cells))

    def test_cells_touching_polygon_boundary_are_included(self) -> None:
        boundary = MultiPolygon(
            [
                Polygon(
                    [
                        (30.0, 55.0),
                        (30.02, 55.0),
                        (30.02, 55.02),
                        (30.0, 55.02),
                        (30.0, 55.0),
                    ]
                )
            ]
        )
        generator = ProjectedGridGenerator(cell_size_meters=1000)

        cells = list(generator.iter_cells(boundary))

        self.assertGreater(len(cells), 0)
        self.assertEqual(cells[0].cell_order, 1)

    def test_high_latitude_region_generates_cells(self) -> None:
        boundary = MultiPolygon(
            [
                Polygon(
                    [
                        (60.0, 75.0),
                        (60.08, 75.0),
                        (60.08, 75.04),
                        (60.0, 75.04),
                        (60.0, 75.0),
                    ]
                )
            ]
        )
        generator = ProjectedGridGenerator(cell_size_meters=1500)

        cells = list(generator.iter_cells(boundary))

        self.assertGreater(len(cells), 0)
        self.assertTrue(all(74.9 < cell.center_lat < 75.2 for cell in cells))

    def test_antimeridian_geometry_generates_normalized_cells(self) -> None:
        boundary = MultiPolygon(
            [
                Polygon(
                    [
                        (179.95, 66.0),
                        (-179.95, 66.0),
                        (-179.95, 66.03),
                        (179.95, 66.03),
                        (179.95, 66.0),
                    ]
                )
            ]
        )
        generator = ProjectedGridGenerator(cell_size_meters=1500)

        cells = list(generator.iter_cells(boundary))

        self.assertGreater(len(cells), 0)
        self.assertTrue(generator.last_context)
        self.assertTrue(generator.last_context.unwrapped)
        self.assertTrue(all(-180 <= cell.center_lon <= 180 for cell in cells))


if __name__ == "__main__":
    unittest.main()
