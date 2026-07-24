from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Coordinate:
    """A geographic coordinate in decimal degrees."""

    lat: float
    lon: float


@dataclass(frozen=True)
class BoundingBox:
    """A north/south/west/east bounding box in decimal degrees."""

    north: float
    south: float
    west: float
    east: float


@dataclass(frozen=True)
class Polygon:
    """A polygon with one outer ring and optional inner holes."""

    outer: tuple[Coordinate, ...]
    holes: tuple[tuple[Coordinate, ...], ...] = ()


@dataclass(frozen=True)
class MultiPolygon:
    """A geographic multipolygon boundary."""

    polygons: tuple[Polygon, ...]


@dataclass(frozen=True)
class GridCell:
    """A rectangular scan cell in decimal degrees."""

    cell_order: int
    north: float
    south: float
    west: float
    east: float
    center_lat: float
    center_lon: float
    status: str = "pending"


@dataclass(frozen=True)
class GridStats:
    """Counters produced while streaming grid cells."""

    candidate_cells: int = 0
    accepted_cells: int = 0


@dataclass(frozen=True)
class ProjectedGridContext:
    """Projection details used for one region grid run."""

    crs_proj4: str
    center_lat: float
    center_lon: float
    unwrapped: bool
