"""Solis Cloud API client."""

import base64
import calendar
import hashlib
import hmac
import json
from datetime import datetime, timezone
from email.utils import formatdate

import requests

BASE_URL = "https://www.soliscloud.com:13333"


def _auth_headers(api_id: str, api_secret: str, body: str, resource: str) -> dict:
    """Build Solis Cloud API authentication headers."""
    content_md5 = base64.b64encode(hashlib.md5(body.encode("utf-8")).digest()).decode("utf-8")
    content_type = "application/json"
    now = datetime.now(timezone.utc)
    date_str = formatdate(timeval=calendar.timegm(now.timetuple()), localtime=False, usegmt=True)

    sign_str = f"POST\n{content_md5}\n{content_type}\n{date_str}\n{resource}"
    signature = base64.b64encode(
        hmac.new(api_secret.encode("utf-8"), sign_str.encode("utf-8"), hashlib.sha1).digest()
    ).decode("utf-8")

    return {
        "Content-MD5": content_md5,
        "Content-Type": content_type,
        "Date": date_str,
        "Authorization": f"API {api_id}:{signature}",
    }


def api_request(api_id: str, api_secret: str, endpoint: str, body: dict) -> dict:
    """Make an authenticated request to the Solis Cloud API."""
    body_json = json.dumps(body)
    headers = _auth_headers(api_id, api_secret, body_json, endpoint)
    resp = requests.post(f"{BASE_URL}{endpoint}", headers=headers, data=body_json)
    resp.raise_for_status()
    result = resp.json()
    if not result.get("success"):
        raise RuntimeError(f"Solis API error: code={result.get('code')} msg={result.get('msg')}")
    return result


def fetch_inverter_day(api_id: str, api_secret: str, inverter_sn: str, date: str, tz: int = 0) -> list[dict]:
    """Fetch inverter time-series data for a specific day.

    Returns list of data points with pac (power W), eToday (daily gen kWh), timeStr, etc.
    """
    body = {"sn": inverter_sn, "money": "GBP", "time": date, "timeZone": tz}
    result = api_request(api_id, api_secret, "/v1/api/inverterDay", body)
    return result.get("data", [])
