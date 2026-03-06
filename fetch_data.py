"""Fetch yesterday's energy data from Octopus Energy and Solis Cloud APIs."""

import base64
import calendar
import hashlib
import hmac
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from email.utils import formatdate

import requests
from dotenv import load_dotenv

load_dotenv()

# --- Octopus Energy ---

OCTOPUS_BASE_URL = "https://api.octopus.energy/v1"


def fetch_octopus_consumption(api_key: str, mpan: str, serial: str, date_from: str, date_to: str) -> list[dict]:
    """Fetch half-hourly consumption data from Octopus Energy.

    Args:
        date_from: ISO 8601 datetime string (inclusive)
        date_to: ISO 8601 datetime string (exclusive)
    """
    url = f"{OCTOPUS_BASE_URL}/electricity-meter-points/{mpan}/meters/{serial}/consumption/"
    params = {
        "period_from": date_from,
        "period_to": date_to,
        "page_size": 100,
        "order_by": "period",
    }

    all_results = []
    while url:
        resp = requests.get(url, params=params, auth=(api_key, ""))
        resp.raise_for_status()
        data = resp.json()
        all_results.extend(data.get("results", []))
        url = data.get("next")
        params = None  # next URL already contains query params

    return all_results


# --- Solis Cloud ---

SOLIS_BASE_URL = "https://www.soliscloud.com:13333"


def _solis_auth_headers(api_id: str, api_secret: str, body: str, canonicalized_resource: str) -> dict:
    """Build Solis Cloud API authentication headers."""
    content_md5 = base64.b64encode(hashlib.md5(body.encode("utf-8")).digest()).decode("utf-8")
    content_type = "application/json"
    now = datetime.now(timezone.utc)
    date_str = formatdate(timeval=calendar.timegm(now.timetuple()), localtime=False, usegmt=True)

    sign_str = f"POST\n{content_md5}\n{content_type}\n{date_str}\n{canonicalized_resource}"
    signature = base64.b64encode(
        hmac.new(api_secret.encode("utf-8"), sign_str.encode("utf-8"), hashlib.sha1).digest()
    ).decode("utf-8")

    return {
        "Content-MD5": content_md5,
        "Content-Type": content_type,
        "Date": date_str,
        "Authorization": f"API {api_id}:{signature}",
    }


def solis_api_request(api_id: str, api_secret: str, endpoint: str, body: dict) -> dict:
    """Make an authenticated request to the Solis Cloud API."""
    body_json = json.dumps(body)
    headers = _solis_auth_headers(api_id, api_secret, body_json, endpoint)
    url = f"{SOLIS_BASE_URL}{endpoint}"

    resp = requests.post(url, headers=headers, data=body_json)
    resp.raise_for_status()
    result = resp.json()

    if not result.get("success"):
        raise RuntimeError(f"Solis API error: code={result.get('code')} msg={result.get('msg')}")

    return result


def fetch_solis_day(api_id: str, api_secret: str, inverter_sn: str, date: str, tz: int = 0) -> dict:
    """Fetch inverter data for a specific day from Solis Cloud.

    Args:
        date: Date string in yyyy-MM-dd format
        tz: Timezone offset in hours (0 for GMT)
    """
    body = {
        "sn": inverter_sn,
        "money": "GBP",
        "time": date,
        "timeZone": tz,
    }
    return solis_api_request(api_id, api_secret, "/v1/api/inverterDay", body)


# --- Main ---


def get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        print(f"Error: {name} environment variable is not set. See .env.example")
        sys.exit(1)
    return value


def find_latest_octopus_date(api_key: str, mpan: str, serial: str) -> str | None:
    """Find the most recent date with available Octopus data (up to 5 days back)."""
    for days_ago in range(1, 6):
        day = datetime.now(timezone.utc) - timedelta(days=days_ago)
        date_str = day.strftime("%Y-%m-%d")
        period_from = f"{date_str}T00:00:00Z"
        period_to = (day + timedelta(days=1)).strftime("%Y-%m-%d") + "T00:00:00Z"
        data = fetch_octopus_consumption(api_key, mpan, serial, period_from, period_to)
        if data:
            return date_str
    return None


def print_octopus_data(label: str, data: list[dict]):
    total = sum(r["consumption"] for r in data)
    print(f"  Periods returned: {len(data)}")
    print(f"  Total {label}: {total:.3f} kWh")
    print(f"  Raw data (first 5 periods):")
    for r in data[:5]:
        print(f"    {r['interval_start']} -> {r['interval_end']}: {r['consumption']:.3f} kWh")
    if len(data) > 5:
        print(f"    ... and {len(data) - 5} more periods")


def main():
    octopus_key = get_required_env("OCTOPUS_API_KEY")
    import_mpan = get_required_env("OCTOPUS_IMPORT_MPAN")
    import_serial = get_required_env("OCTOPUS_IMPORT_SERIAL")
    export_mpan = get_required_env("OCTOPUS_EXPORT_MPAN")
    export_serial = get_required_env("OCTOPUS_EXPORT_SERIAL")
    solis_id = get_required_env("SOLIS_API_ID")
    solis_secret = get_required_env("SOLIS_API_SECRET")
    solis_sn = get_required_env("SOLIS_INVERTER_SN")
    solis_tz = int(os.getenv("SOLIS_TIMEZONE", "0"))

    # Find the latest date with Octopus data (often ~24h lag)
    print("Finding latest available Octopus data...")
    date_str = find_latest_octopus_date(octopus_key, import_mpan, import_serial)
    if not date_str:
        print("No Octopus data found in the last 5 days. Check your credentials.")
        sys.exit(1)

    period_from = f"{date_str}T00:00:00Z"
    next_day = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    period_to = f"{next_day}T00:00:00Z"

    print(f"\nFetching energy data for {date_str}")
    print("=" * 60)

    # --- Octopus Energy: Import ---
    print("\n--- Octopus Energy: Grid Import ---")
    try:
        import_data = fetch_octopus_consumption(octopus_key, import_mpan, import_serial, period_from, period_to)
        print_octopus_data("import", import_data)
    except Exception as e:
        print(f"  Error: {e}")

    # --- Octopus Energy: Export ---
    print("\n--- Octopus Energy: Grid Export ---")
    try:
        export_data = fetch_octopus_consumption(octopus_key, export_mpan, export_serial, period_from, period_to)
        print_octopus_data("export", export_data)
    except Exception as e:
        print(f"  Error: {e}")

    # --- Solis Cloud: Solar Generation ---
    print("\n--- Solis Cloud: Solar Generation ---")
    try:
        solis_data = fetch_solis_day(solis_id, solis_secret, solis_sn, date_str, solis_tz)
        data_points = solis_data.get("data", [])
        print(f"  Data points returned: {len(data_points)}")
        if data_points:
            last_point = data_points[-1]
            print(f"  Daily generation (eToday): {last_point.get('eToday', 'N/A')} kWh")
            print(f"  Total generation (eTotal): {last_point.get('eTotal', 'N/A')} kWh")
            print(f"  Raw data (first 5 points):")
            for point in data_points[:5]:
                print(f"    {point.get('timeStr', 'N/A')}: pac={point.get('pac', 'N/A')}W, eToday={point.get('eToday', 'N/A')} kWh")
            if len(data_points) > 5:
                print(f"    ... and {len(data_points) - 5} more points")
        else:
            print("  No generation data returned for this day")
    except Exception as e:
        print(f"  Error: {e}")

    print("\n" + "=" * 60)
    print("Done.")


if __name__ == "__main__":
    main()
