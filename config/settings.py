"""
Основные настройки Beauty Salon Agent.
Здесь хранятся все параметры проекта.
"""

from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

load_dotenv(dotenv_path=ENV_FILE, override=False)

# ================================
# Google Sheets
# ================================

SPREADSHEET_NAME = "Beauty Salon Database"

# ================================
# География
# ================================

SCAN_ORDER = "WEST_TO_EAST_NORTH_TO_SOUTH"

GRID_SIZE_METERS = 1500

GRID_GENERATOR_VERSION = "2.0.0"

GRID_INSERT_BATCH_SIZE = 1000

BOUNDARY_CACHE_DIRECTORY = "data/boundaries"

OSM_OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
]

OSM_TIMEOUT_SECONDS = 180

OSM_MAX_RETRIES = 3

OSM_BACKOFF_SECONDS = 2.0

OSM_USER_AGENT = (
    "BeautySalonAgent/1.0 "
    "(production-grid-generator; contact: local-operator)"
)

# ================================
# Поиск
# ================================

SEARCH_QUERIES = [
    "маникюр",
    "салон красоты маникюр",
    "студия маникюра",
    "ногтевая студия",
    "nail studio",
]

# ================================
# Повторы
# ================================

MAX_RETRIES = 3

# ================================
# 2GIS Scanner
# ================================

TWOGIS_API_KEY_ENV = "TWOGIS_API_KEY"

TWOGIS_PLACES_ENDPOINT = "https://catalog.api.2gis.com/3.0/items"

TWOGIS_DETAILS_ENDPOINT = "https://catalog.api.2gis.com/3.0/items/byid"

TWOGIS_USER_AGENT = (
    "BeautySalonAgent/1.0 "
    "(2gis-salon-scanner; contact: local-operator)"
)

TWOGIS_TIMEOUT_SECONDS = 30

TWOGIS_DETAILS_TIMEOUT_SECONDS = 30

TWOGIS_MAX_RETRIES = 3

TWOGIS_DETAILS_RETRY_LIMIT = 3

TWOGIS_BACKOFF_SECONDS = 1.5

TWOGIS_RATE_LIMIT_DELAY_SECONDS = 1.0

TWOGIS_PAGE_SIZE = 10

TWOGIS_MAX_PAGES_PER_QUERY = 1

SCANNER_MAX_CELLS_PER_RUN = 1

SCANNER_CELL_RETRY_LIMIT = 3

SCANNER_DRY_RUN = True

# ================================
# Enrichment
# ================================

ENRICHMENT_DRY_RUN = True

ENRICHMENT_MAX_ORGANIZATIONS_PER_RUN = 1

ENRICHMENT_REFRESH_AFTER_DAYS = 30

DETAIL_PARSER_VERSION = "1.0.0"

# ================================
# Pricing
# ================================

PRICING_DRY_RUN = True

PRICING_MAX_SALONS_PER_RUN = 1

PRICING_MAX_PAGES_PER_SALON = 4

PRICING_TIMEOUT_SECONDS = 15

PRICING_MAX_RESPONSE_BYTES = 1_000_000

PRICING_RETRY_LIMIT = 2

PRICING_USER_AGENT = (
    "BeautySalonAgent/1.0 "
    "(manicure-price-extractor; contact: local-operator)"
)

PRICE_PARSER_VERSION = "1.0.0"

# ================================
# Reclassification
# ================================

RECLASSIFICATION_DRY_RUN = True

RECLASSIFICATION_MAX_RECORDS_PER_RUN = 25

SALON_CLASSIFIER_VERSION = "2.0.0"

# ================================
# Export
# ================================

EXPORT_DRY_RUN = True

EXPORT_INCLUDE_REJECTED = True

EXPORT_OUTPUT_DIR = "exports"

# ================================
# Global Agent Orchestration
# ================================

AGENT_DRY_RUN = True

AGENT_MAX_REGIONS_PER_RUN = 1

AGENT_MAX_CELLS_PER_RUN = 1

AGENT_MAX_ENRICHMENTS_PER_RUN = 1

AGENT_MAX_PRICE_CHECKS_PER_RUN = 1

AGENT_EXPORT_AFTER_RUN = False

AGENT_ENABLE_GRID = True

AGENT_ENABLE_SCANNING = True

AGENT_ENABLE_RECLASSIFICATION = True

AGENT_ENABLE_ENRICHMENT = False

AGENT_ENABLE_PRICING = False

AGENT_ENABLE_EXPORT = False

AGENT_STOP_ON_STAGE_ERROR = True

AGENT_STALE_LOCK_MINUTES = 30

AGENT_STALE_PROCESSING_MINUTES = 60
