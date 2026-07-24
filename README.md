# Beauty Salon Agent

Production-oriented scanner for beauty and nail salons across Russian regions.

## Current Capabilities

- SQLite schema and region orchestration.
- 89 configured regions in west-to-east scan order.
- OSM administrative-boundary resolution through Overpass.
- Local boundary cache under `data/boundaries/`.
- Projected 1500m grid generation with Shapely and pyproj.
- Grid-generation metadata for safe idempotency and partial-run recovery.
- Resumable 2GIS salon scanning pipeline behind a provider interface.
- Deterministic manicure-salon classifier and duplicate merging.

## Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python src/main.py
```

The command initializes SQLite, selects the active region, loads or fetches its
OSM boundary, creates grid cells if a complete grid does not already exist, and
then runs the 2GIS scanner according to the safe development limits in
`config/settings.py`.

By default, `SCANNER_DRY_RUN = True` and `SCANNER_MAX_CELLS_PER_RUN = 1`, so no
2GIS requests are made accidentally. To enable real 2GIS scanning, configure an
official 2GIS Places API key:

```bash
export TWOGIS_API_KEY="your-official-2gis-api-key"
```

Then set `SCANNER_DRY_RUN = False` in `config/settings.py`.

## Boundary Cache

Boundaries are cached as GeoJSON-like JSON files in:

```text
data/boundaries/
```

Each cache file stores the region name, OSM relation id, source endpoint,
fetch timestamp, OSM metadata when available, normalized geometry, and raw
relation payload.

## Tests

Tests do not call external services.

```bash
PYTHONPATH=src python -m unittest discover -s tests
```
