# Israel Building Plans Finder (POC)

Search for building plans (היתרי בנייה, תוכניות בניין עיר) and street-level images by Israeli address.

## Features

- **Building plans search** via layered city source registry:
  - Tel Aviv: engineering archive (5.3M+ documents) via GIS open-data API
  - Jerusalem + all other cities: XPLAN national planning database
  - MAVAT fallback with deep-link to interactive viewer
- **Street-level images** from Wikimedia Commons (free), Mapillary (free), and Google Street View (optional)
- **Copy & download** any street image directly from the UI (clipboard or file save)
- **Dual interface**: Web UI (Hebrew RTL) + CLI with Rich tables
- **SQLite cache** with TTL-based expiry
- **All free APIs** — no paid services required

## Quick Start

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# (Optional) Configure API keys in .env
cp .env.example .env
# Edit .env with your Mapillary token / Google SV key

# Start the web server
uvicorn app.main:app --reload

# Open http://localhost:8000 in your browser
```

## CLI Usage

```bash
# Full search (plans + images)
python cli.py search "דיזנגוף 50, תל אביב"

# Plans only
python cli.py search "בן יהודה 10, ירושלים" --plans-only

# Images only
python cli.py search "הרצל 1, חיפה" --images-only

# List registered city sources
python cli.py sources

# Cache management
python cli.py cache stats
python cli.py cache clear
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/search?q=...` | GET | Search by address |
| `/api/streetview/image?lat=&lon=&heading=` | GET | Proxy Street View image (hides API key) |
| `/api/streetview/download?lat=&lon=&heading=` | GET | Download Street View image as file |
| `/api/sources` | GET | List registered city sources |
| `/api/cache/stats` | GET | Cache statistics |
| `/api/cache` | DELETE | Clear cache |
| `/docs` | GET | Interactive API docs (Swagger) |

## Adding a New City

1. Add an entry to `sources.json`:
   ```json
   "חיפה": {
     "sources": ["haifa_gis", "xplan", "mavat"],
     "notes": "Haifa municipality GIS"
   }
   ```

2. Create an adapter in `app/services/adapters/haifa_gis.py`:
   ```python
   from app.services.source_registry import SourceAdapter, register_adapter

   @register_adapter
   class HaifaGISAdapter(SourceAdapter):
       @property
       def name(self) -> str:
           return "haifa_gis"
       # ... implement search()
   ```

3. Import it in `app/services/adapters/__init__.py`

## Data Sources

| Source | Coverage | API Type | Cost |
|--------|----------|----------|------|
| Tel Aviv GIS | Tel Aviv-Yafo | REST/SOAP | Free |
| XPLAN | All of Israel | ArcGIS REST | Free |
| MAVAT | All of Israel | Web link | Free |
| Nominatim | Global | REST | Free |
| Wikimedia Commons | Global | REST | Free (no key) |
| Mapillary | Global | REST | Free (token) |
| Google Street View | Global | REST | Free (10K/mo, key) |

## Project Structure

```
├── cli.py                    # CLI entry point
├── sources.json              # City source registry config
├── requirements.txt
├── app/
│   ├── main.py               # FastAPI entry point
│   ├── config.py             # Settings
│   ├── db.py                 # SQLite cache
│   ├── orchestrator.py       # Shared search logic
│   ├── routers/
│   │   └── search.py         # API endpoints
│   ├── services/
│   │   ├── geocoder.py       # Nominatim geocoding
│   │   ├── street_imagery.py # Wikimedia + Mapillary + Google SV
│   │   ├── source_registry.py # Adapter base + registry
│   │   └── adapters/
│   │       ├── tlv_archive.py  # Tel Aviv GIS
│   │       ├── xplan.py        # XPLAN national
│   │       └── mavat.py        # MAVAT fallback
│   ├── models/
│   │   └── schemas.py        # Pydantic models
│   └── static/               # Web UI files
```
