"""Octopus Energy API client."""

import requests

BASE_URL = "https://api.octopus.energy/v1"


def fetch_consumption(api_key: str, mpan: str, serial: str, period_from: str, period_to: str) -> list[dict]:
    """Fetch half-hourly consumption data. Returns list of {consumption, interval_start, interval_end}."""
    url = f"{BASE_URL}/electricity-meter-points/{mpan}/meters/{serial}/consumption/"
    params = {
        "period_from": period_from,
        "period_to": period_to,
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
        params = None
    return all_results


def fetch_account(api_key: str, account_number: str) -> dict:
    """Fetch account details including tariff agreements."""
    resp = requests.get(f"{BASE_URL}/accounts/{account_number}/", auth=(api_key, ""))
    resp.raise_for_status()
    return resp.json()


def _extract_product_code(tariff_code: str) -> str:
    """Extract product code from a tariff code.

    E-2R-VAR-22-11-01-J -> VAR-22-11-01
    E-1R-OUTGOING-VAR-24-10-26-J -> OUTGOING-VAR-24-10-26
    """
    parts = tariff_code.split("-")
    # Remove prefix (E, 1R/2R) and suffix (region letter)
    return "-".join(parts[2:-1])


def get_active_tariffs(api_key: str, account_number: str, target_date: str) -> dict:
    """Get active import and export tariff info for a given date.

    Returns dict with 'import' and 'export' keys, each containing:
        tariff_code, product_code, is_economy7
    """
    account = fetch_account(api_key, account_number)
    result = {"import": None, "export": None}

    for prop in account.get("properties", []):
        for meter_point in prop.get("electricity_meter_points", []):
            is_export = meter_point.get("is_export", False)
            for agreement in meter_point.get("agreements", []):
                valid_from = agreement["valid_from"][:10]
                valid_to = agreement.get("valid_to")
                if valid_to:
                    valid_to = valid_to[:10]
                if valid_from <= target_date and (valid_to is None or valid_to > target_date):
                    tariff_code = agreement["tariff_code"]
                    product_code = _extract_product_code(tariff_code)
                    # E-2R means 2-register (Economy 7 day/night)
                    is_economy7 = tariff_code.startswith("E-2R-")
                    key = "export" if is_export else "import"
                    result[key] = {
                        "tariff_code": tariff_code,
                        "product_code": product_code,
                        "is_economy7": is_economy7,
                    }
    return result


def fetch_rates(product_code: str, tariff_code: str, period_from: str, period_to: str, is_economy7: bool) -> dict:
    """Fetch tariff rates for a given period.

    Returns dict with rate info. For Economy 7:
        {day_rate, night_rate, standing_charge} (all in p/kWh inc VAT)
    For standard:
        {unit_rate, standing_charge}
    """
    base = f"{BASE_URL}/products/{product_code}/electricity-tariffs/{tariff_code}"
    result = {}

    if is_economy7:
        for rate_type, key in [("day-unit-rates", "day_rate"), ("night-unit-rates", "night_rate")]:
            resp = requests.get(f"{base}/{rate_type}/", params={
                "period_from": period_from, "period_to": period_to, "page_size": 10,
            })
            resp.raise_for_status()
            rates = resp.json().get("results", [])
            # Pick the DIRECT_DEBIT rate if multiple
            for r in rates:
                if r.get("payment_method") in ("DIRECT_DEBIT", None):
                    result[key] = r["value_inc_vat"]
                    break
            if key not in result and rates:
                result[key] = rates[0]["value_inc_vat"]
    else:
        resp = requests.get(f"{base}/standard-unit-rates/", params={
            "period_from": period_from, "period_to": period_to, "page_size": 100,
        })
        resp.raise_for_status()
        rates = resp.json().get("results", [])
        result["rates"] = rates
        if rates:
            for r in rates:
                if r.get("payment_method") in ("DIRECT_DEBIT", None):
                    result["unit_rate"] = r["value_inc_vat"]
                    break

    # Standing charge
    resp = requests.get(f"{base}/standing-charges/", params={
        "period_from": period_from, "period_to": period_to, "page_size": 10,
    })
    resp.raise_for_status()
    charges = resp.json().get("results", [])
    for c in charges:
        if c.get("payment_method") in ("DIRECT_DEBIT", None):
            result["standing_charge"] = c["value_inc_vat"]
            break
    if "standing_charge" not in result and charges:
        result["standing_charge"] = charges[0]["value_inc_vat"]

    return result


def fetch_export_rates(product_code: str, tariff_code: str, period_from: str, period_to: str) -> float:
    """Fetch export unit rate in p/kWh."""
    base = f"{BASE_URL}/products/{product_code}/electricity-tariffs/{tariff_code}"
    resp = requests.get(f"{base}/standard-unit-rates/", params={
        "period_from": period_from, "period_to": period_to, "page_size": 10,
    })
    resp.raise_for_status()
    rates = resp.json().get("results", [])
    if rates:
        # Export rates don't have VAT
        return rates[0]["value_inc_vat"]
    return 0.0
