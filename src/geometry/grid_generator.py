from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Iterator
from dataclasses import replace

from pyproj import CRS, Transformer
from shapely.geometry import Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform
from shapely.prepared import prep

from .models import GridCell, GridStats, ProjectedGridContext

ProgressLogger = Callable[[str], None]


class ProjectedGridGenerator:
    """Generate true square grid cells in a local projected CRS."""

    def __init__(
        self,
        cell_size_meters: float,
        progress_logger: ProgressLogger | None = None,
    ) -> None:
        if cell_size_meters <= 0:
            raise ValueError("Cell size must be greater than zero.")

        self.cell_size_meters = cell_size_meters
        self.progress_logger = progress_logger or (lambda message: None)
        self.last_stats = GridStats()
        self.last_context: ProjectedGridContext | None = None

    def iter_cells(self, boundary: BaseGeometry) -> Iterator[GridCell]:
        """
        Stream cells intersecting a WGS84 boundary.

        The boundary is unwrapped around the antimeridian when needed, projected
        to a local azimuthal-equidistant CRS, gridded in meters, and transformed
        back to WGS84 for storage.
        """

        if boundary.is_empty:
            raise ValueError("Cannot generate a grid for empty geometry.")

        wgs84_boundary, unwrapped = unwrap_antimeridian(boundary)
        projected_boundary, context, inverse_transformer = self._project_boundary(
            wgs84_boundary,
            unwrapped=unwrapped,
        )
        prepared_boundary = prep(projected_boundary)
        min_x, min_y, max_x, max_y = projected_boundary.bounds

        self.last_context = context
        self.last_stats = GridStats()
        self.progress_logger(f"Projected CRS: {context.crs_proj4}")

        cell_order = 0
        y = min_y

        while y < max_y:
            next_y = min(y + self.cell_size_meters, max_y)
            x = min_x

            while x < max_x:
                next_x = min(x + self.cell_size_meters, max_x)
                candidate = box(x, y, next_x, next_y)
                self.last_stats = replace(
                    self.last_stats,
                    candidate_cells=self.last_stats.candidate_cells + 1,
                )

                if prepared_boundary.intersects(candidate):
                    cell_order += 1
                    self.last_stats = replace(
                        self.last_stats,
                        accepted_cells=self.last_stats.accepted_cells + 1,
                    )
                    yield self._to_grid_cell(
                        cell_order=cell_order,
                        projected_cell=candidate,
                        inverse_transformer=inverse_transformer,
                        projection_center_lon=context.center_lon,
                    )

                x = next_x

            y = next_y

    def _project_boundary(
        self,
        boundary: BaseGeometry,
        unwrapped: bool,
    ) -> tuple[BaseGeometry, ProjectedGridContext, Transformer]:
        centroid = boundary.representative_point()
        center_lat = float(centroid.y)
        center_lon = float(centroid.x)
        crs_proj4 = (
            f"+proj=aeqd +lat_0={center_lat:.12f} "
            f"+lon_0={center_lon:.12f} +datum=WGS84 +units=m +no_defs"
        )
        projected_crs = CRS.from_proj4(crs_proj4)
        wgs84_crs = CRS.from_epsg(4326)
        forward_transformer = Transformer.from_crs(
            wgs84_crs,
            projected_crs,
            always_xy=True,
        )
        inverse_transformer = Transformer.from_crs(
            projected_crs,
            wgs84_crs,
            always_xy=True,
        )
        projected_boundary = transform(forward_transformer.transform, boundary)

        context = ProjectedGridContext(
            crs_proj4=crs_proj4,
            center_lat=center_lat,
            center_lon=normalize_longitude(center_lon),
            unwrapped=unwrapped,
        )

        return projected_boundary, context, inverse_transformer

    def _to_grid_cell(
        self,
        cell_order: int,
        projected_cell: Polygon,
        inverse_transformer: Transformer,
        projection_center_lon: float,
    ) -> GridCell:
        min_x, min_y, max_x, max_y = projected_cell.bounds
        center_x = (min_x + max_x) / 2
        center_y = (min_y + max_y) / 2
        center_lon, center_lat = inverse_transformer.transform(
            center_x,
            center_y,
        )
        center_lon = normalize_longitude(center_lon)

        corner_lons: list[float] = []
        corner_lats: list[float] = []

        for x, y in (
            (min_x, min_y),
            (min_x, max_y),
            (max_x, max_y),
            (max_x, min_y),
        ):
            lon, lat = inverse_transformer.transform(x, y)
            corner_lons.append(unwrap_longitude(lon, projection_center_lon))
            corner_lats.append(lat)

        west = normalize_longitude(min(corner_lons))
        east = normalize_longitude(max(corner_lons))

        return GridCell(
            cell_order=cell_order,
            north=max(corner_lats),
            south=min(corner_lats),
            west=west,
            east=east,
            center_lat=center_lat,
            center_lon=center_lon,
        )


def unwrap_antimeridian(geometry: BaseGeometry) -> tuple[BaseGeometry, bool]:
    """Return geometry with longitudes unwrapped around its circular center."""

    longitudes = _collect_longitudes(geometry)

    if not longitudes:
        return geometry, False

    circular_center = circular_mean_longitude(longitudes)
    regular_width = max(longitudes) - min(longitudes)
    unwrapped_longitudes = [
        unwrap_longitude(longitude, circular_center)
        for longitude in longitudes
    ]
    unwrapped_width = max(unwrapped_longitudes) - min(unwrapped_longitudes)

    if regular_width <= 180 or unwrapped_width >= regular_width:
        return geometry, False

    return (
        transform(
            lambda x, y, z=None: (_map_longitudes(x, circular_center), y),
            geometry,
        ),
        True,
    )


def normalize_longitude(longitude: float) -> float:
    """Normalize longitude into the [-180, 180] range."""

    normalized = ((longitude + 180) % 360) - 180

    if normalized == -180 and longitude > 0:
        return 180.0

    return normalized


def unwrap_longitude(longitude: float, reference_longitude: float) -> float:
    """Shift longitude by 360-degree turns near a reference longitude."""

    unwrapped = longitude

    while unwrapped - reference_longitude > 180:
        unwrapped -= 360

    while unwrapped - reference_longitude < -180:
        unwrapped += 360

    return unwrapped


def circular_mean_longitude(longitudes: list[float]) -> float:
    """Calculate a circular mean for longitudes."""

    sin_sum = sum(math.sin(math.radians(longitude)) for longitude in longitudes)
    cos_sum = sum(math.cos(math.radians(longitude)) for longitude in longitudes)

    if abs(sin_sum) < 1e-12 and abs(cos_sum) < 1e-12:
        return 0.0

    return math.degrees(math.atan2(sin_sum, cos_sum))


def _collect_longitudes(geometry: BaseGeometry) -> list[float]:
    longitudes: list[float] = []

    def collect(
        x: object,
        y: object,
        z: object | None = None,
    ) -> tuple[object, object]:
        if _is_coordinate_sequence(x):
            longitudes.extend(float(value) for value in x)
        else:
            longitudes.append(float(x))

        return x, y

    transform(collect, geometry)
    return longitudes


def _map_longitudes(x: object, reference_longitude: float) -> object:
    if _is_coordinate_sequence(x):
        return [
            unwrap_longitude(float(value), reference_longitude)
            for value in x
        ]

    return unwrap_longitude(float(x), reference_longitude)


def _is_coordinate_sequence(value: object) -> bool:
    return isinstance(value, Iterable) and not isinstance(value, (str, bytes))
