# Israel Address Building Plans Finder

Search Israeli building plans, permits, and street images by address. Aggregates data from multiple municipal sources (Tel Aviv Archive, XPlan, Mavat) with geocoding, caching, and parallel lookups.

## Features

- **Geocoding** -- resolve Hebrew addresses to coordinates via Nominatim
- **Building plans** -- query municipal plan databases by city with a pluggable source registry
- **Street imagery** -- fetch Mapillary and Google Street View images near the address
- **Caching** -- SQLite-backed cache with configurable TTL to avoid redundant lookups
- **Web UI** -- FastAPI server with a static frontend
- **CLI** -- Rich-powered terminal interface

## Quickstart

```bash
# Clone and set up
git clone https://github.com/shayke-cohen/AmitAddress.git
cd AmitAddress
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# (Optional) configure API keys for street imagery
cp .env.example .env
# edit .env with your MAPILLARY_CLIENT_TOKEN and/or GOOGLE_STREETVIEW_API_KEY
```

### CLI

```bash
python cli.py search "דיזנגוף 50 תל אביב"
python cli.py sources        # list registered city sources
python cli.py cache stats    # show cache statistics
python cli.py cache clear    # clear cached results
```

### Web Server

```bash
uvicorn app.main:app --reload
# Open http://localhost:8000 (UI) or http://localhost:8000/docs (API docs)
```

## Configuration

All settings are optional and loaded from environment variables or a `.env` file:

| Variable | Description |
|----------|-------------|
| `MAPILLARY_CLIENT_TOKEN` | Mapillary API token for street-level imagery |
| `GOOGLE_STREETVIEW_API_KEY` | Google Street View API key |

## Project Structure

```
├── cli.py              # CLI entry point (click + rich)
├── sources.json        # City-to-source mapping
├── requirements.txt    # Python dependencies
├── app/
│   ├── main.py         # FastAPI app
│   ├── orchestrator.py # Shared search pipeline
│   ├── config.py       # Settings (pydantic-settings)
│   ├── db.py           # SQLite cache layer
│   ├── models/         # Pydantic schemas
│   ├── routers/        # API routes
│   ├── services/       # Geocoder, adapters, street imagery
│   └── static/         # Web frontend
```

## License

MIT
