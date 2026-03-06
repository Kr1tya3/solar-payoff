# Solar Payoff - Project Guide

## Purpose
Track solar panel ROI by combining data from two APIs:
- **Octopus Energy API** - UK energy provider; provides half-hourly import/export meter readings
- **Solis Cloud API** - Inverter manufacturer; provides solar generation data

The goal is a daily-updated dashboard showing solar usage, money saved (self-consumption avoiding import), and money earned (export payments).

## Architecture
- Python 3.12+ application managed with `uv`
- Configuration via `.env` file (never committed - in .gitignore)
- Dependencies: `requests`, `python-dotenv` (managed in pyproject.toml)

## API Details

### Octopus Energy API
- Base URL: `https://api.octopus.energy/v1/`
- Auth: HTTP Basic Auth with API key as username, empty password
- Electricity consumption: `GET /v1/electricity-meter-points/{mpan}/meters/{serial}/consumption/`
- Query params: `period_from`, `period_to` (ISO 8601 with Z suffix), `page_size`, `order_by=period`
- Returns half-hourly intervals with `consumption` (kWh), `interval_start`, `interval_end`
- User needs: API key, MPAN, meter serial number (for both import and export meters)

### Solis Cloud API
- Base URL: `https://www.soliscloud.com:13333`
- Auth: HMAC-SHA1 signature in Authorization header
  - Sign = base64(HmacSHA1(apiSecret, "POST\n" + Content-MD5 + "\n" + Content-Type + "\n" + Date + "\n" + CanonicalizedResource))
  - Authorization: `API {apiId}:{sign}`
  - Content-MD5: base64(md5(body))
  - Date: RFC 2822 GMT format (must be within 15 min of server time)
  - All requests are POST with JSON body
- Inverter daily data: `/v1/api/inverterDay` - params: `sn`, `money` (e.g. "GBP"), `time` (yyyy-MM-dd), `timeZone`
- Inverter list: `/v1/api/inverterList` - params: `pageNo`, `pageSize`
- Inverter detail: `/v1/api/inverterDetail` - params: `sn` or `id`
- Returns arrays of time-series data points with `pac` (real-time power), `eToday` (daily generation)

## Environment Variables (.env)
```
OCTOPUS_API_KEY=
OCTOPUS_IMPORT_MPAN=
OCTOPUS_IMPORT_SERIAL=
OCTOPUS_EXPORT_MPAN=
OCTOPUS_EXPORT_SERIAL=
SOLIS_API_ID=
SOLIS_API_SECRET=
SOLIS_INVERTER_SN=
SOLIS_TIMEZONE=0
```

## Commands
- Run: `uv run fetch_data.py`
- Add dependency: `uv add <package>`
- Sync venv: `uv sync`
