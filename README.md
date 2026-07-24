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
- Controlled 2GIS organization-details enrichment for accepted salons.
- Deterministic manicure price extraction with evidence tracking.

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

## Details Enrichment

Module 5 enriches already accepted 2GIS salons through the official Places API
details endpoint (`/3.0/items/byid`). It stores every raw details response in
`organization_detail_results` and maintains deduplicated current contacts in
`salon_contacts`.

The default development settings are safe:

```python
ENRICHMENT_DRY_RUN = True
ENRICHMENT_MAX_ORGANIZATIONS_PER_RUN = 1
```

Run a dry-run preview:

```bash
PYTHONPATH=src python3 src/enrich.py
```

Run one controlled live details request only after `TWOGIS_API_KEY` is
configured:

```bash
PYTHONPATH=src python3 src/enrich.py --live --max 1
```

The normal application command, `python src/main.py`, still performs grid
creation and scanner orchestration only; details enrichment is intentionally a
separate controlled step.

## Price Extraction

Module 6 extracts the target service price, "basic manicure with coating",
only from structured provider evidence already saved in SQLite or directly
attributable content from a salon's saved website URL. It does not scrape
social networks, run browser automation, use search engines, or infer prices
from unrelated services.

The default development settings are safe:

```python
PRICING_DRY_RUN = True
PRICING_MAX_SALONS_PER_RUN = 1
PRICING_MAX_PAGES_PER_SALON = 4
```

Run a dry-run preview:

```bash
python3 src/prices.py
```

Run one controlled live website/provider extraction:

```bash
python3 src/prices.py --live --max 1
```

Pricing writes append-only audit rows to `price_check_results` and maintains
the current active target price in `salon_prices`. If no reliable target price
is found, it records a clear `not_found` result rather than guessing.

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
