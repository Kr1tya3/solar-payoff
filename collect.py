"""Collect energy data and store in the database.

Usage:
    uv run collect.py              # Collect latest available day
    uv run collect.py --backfill   # Backfill all available historical data
    uv run collect.py --date 2026-03-01  # Collect a specific date
"""

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

import db
import octopus
import solis

load_dotenv()

NIGHT_START = float(os.getenv("ECONOMY7_NIGHT_START", "0.5"))
NIGHT_END = float(os.getenv("ECONOMY7_NIGHT_END", "7.5"))


def get_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        print(f"Error: {name} not set. See .env.example")
        sys.exit(1)
    return value


def is_night(interval_start: str) -> bool:
    dt = datetime.fromisoformat(interval_start.replace("Z", "+00:00"))
    hour = dt.hour + dt.minute / 60.0
    return NIGHT_START <= hour < NIGHT_END


def collect_day(date_str: str, config: dict, conn) -> bool:
    """Collect and store data for a single date. Returns True if data was found."""
    period_from = f"{date_str}T00:00:00Z"
    next_day = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    period_to = f"{next_day}T00:00:00Z"

    # Fetch Octopus consumption
    import_data = octopus.fetch_consumption(
        config["api_key"], config["import_mpan"], config["import_serial"], period_from, period_to
    )
    if not import_data:
        return False

    export_data = octopus.fetch_consumption(
        config["api_key"], config["export_mpan"], config["export_serial"], period_from, period_to
    )

    # Fetch tariff rates
    tariffs = octopus.get_active_tariffs(config["api_key"], config["account"], date_str)
    import_tariff = tariffs["import"]
    import_rates = octopus.fetch_rates(
        import_tariff["product_code"], import_tariff["tariff_code"],
        period_from, period_to, import_tariff["is_economy7"],
    )
    export_tariff = tariffs["export"]
    export_rate = octopus.fetch_export_rates(
        export_tariff["product_code"], export_tariff["tariff_code"],
        period_from, period_to,
    )

    # Fetch solar data
    # Rate limit: 2 req/sec for Solis
    time.sleep(0.5)
    solar_points = solis.fetch_inverter_day(
        config["solis_id"], config["solis_secret"], config["solis_sn"],
        date_str, config["solis_tz"],
    )
    solar_gen = solar_points[-1].get("eToday", 0) if solar_points else 0

    # Calculate costs
    total_import = sum(r["consumption"] for r in import_data)
    total_export = sum(r["consumption"] for r in export_data)
    self_consumption = solar_gen - total_export

    day_rate = import_rates.get("day_rate", import_rates.get("unit_rate", 0))
    night_rate = import_rates.get("night_rate", day_rate)

    day_kwh = night_kwh = day_cost = night_cost = 0.0
    for r in import_data:
        kwh = r["consumption"]
        if is_night(r["interval_start"]):
            night_kwh += kwh
            night_cost += kwh * night_rate
        else:
            day_kwh += kwh
            day_cost += kwh * day_rate

    standing_charge = import_rates.get("standing_charge", 0)
    export_earnings = total_export * export_rate
    solar_savings = self_consumption * day_rate

    # Store daily summary
    db.upsert_daily_summary(conn, {
        "date": date_str,
        "import_kwh": round(total_import, 3),
        "export_kwh": round(total_export, 3),
        "generation_kwh": round(solar_gen, 3),
        "self_consumption_kwh": round(self_consumption, 3),
        "day_import_kwh": round(day_kwh, 3),
        "night_import_kwh": round(night_kwh, 3),
        "import_cost_pence": round(day_cost + night_cost, 2),
        "day_cost_pence": round(day_cost, 2),
        "night_cost_pence": round(night_cost, 2),
        "standing_charge_pence": round(standing_charge, 2),
        "export_earnings_pence": round(export_earnings, 2),
        "solar_savings_pence": round(solar_savings, 2),
        "import_day_rate": day_rate,
        "import_night_rate": night_rate,
        "export_rate": export_rate,
    })

    # Store half-hourly detail
    export_by_period = {r["interval_start"]: r["consumption"] for r in export_data}
    hh_rows = []
    for r in import_data:
        start = r["interval_start"]
        night_flag = is_night(start)
        rate = night_rate if night_flag else day_rate
        hh_rows.append({
            "date": date_str,
            "interval_start": start,
            "import_kwh": round(r["consumption"], 3),
            "export_kwh": round(export_by_period.get(start, 0), 3),
            "is_night": 1 if night_flag else 0,
            "rate_p_kwh": rate,
        })
    db.upsert_half_hourly(conn, hh_rows)

    # Store solar 5-min detail
    solar_rows = []
    for p in solar_points:
        time_str = p.get("time", p.get("timeStr", ""))
        solar_rows.append({
            "date": date_str,
            "time_str": time_str,
            "pac_watts": p.get("pac", 0),
            "e_today_kwh": p.get("eToday", 0),
        })
    if solar_rows:
        db.upsert_solar_5min(conn, solar_rows)

    conn.commit()
    return True


def find_available_dates(config: dict) -> list[str]:
    """Find all dates with available Octopus data."""
    dates = []
    for days_ago in range(1, 60):  # Look back up to 60 days
        day = datetime.now(timezone.utc) - timedelta(days=days_ago)
        date_str = day.strftime("%Y-%m-%d")
        period_from = f"{date_str}T00:00:00Z"
        period_to = (day + timedelta(days=1)).strftime("%Y-%m-%d") + "T00:00:00Z"
        data = octopus.fetch_consumption(
            config["api_key"], config["import_mpan"], config["import_serial"],
            period_from, period_to,
        )
        if data:
            dates.append(date_str)
        else:
            # If we get no data after finding some, we've hit the limit
            if dates:
                break
    return sorted(dates)


def main():
    parser = argparse.ArgumentParser(description="Collect energy data")
    parser.add_argument("--backfill", action="store_true", help="Backfill all available historical data")
    parser.add_argument("--date", type=str, help="Collect a specific date (YYYY-MM-DD)")
    args = parser.parse_args()

    config = {
        "api_key": get_env("OCTOPUS_API_KEY"),
        "account": get_env("OCTOPUS_ACCOUNT_NUMBER"),
        "import_mpan": get_env("OCTOPUS_IMPORT_MPAN"),
        "import_serial": get_env("OCTOPUS_IMPORT_SERIAL"),
        "export_mpan": get_env("OCTOPUS_EXPORT_MPAN"),
        "export_serial": get_env("OCTOPUS_EXPORT_SERIAL"),
        "solis_id": get_env("SOLIS_API_ID"),
        "solis_secret": get_env("SOLIS_API_SECRET"),
        "solis_sn": get_env("SOLIS_INVERTER_SN"),
        "solis_tz": int(os.getenv("SOLIS_TIMEZONE", "0")),
    }

    db.init_db()
    conn = db.get_connection()

    if args.date:
        print(f"Collecting data for {args.date}...")
        if collect_day(args.date, config, conn):
            print(f"  Done: {args.date}")
        else:
            print(f"  No data available for {args.date}")

    elif args.backfill:
        print("Finding available dates...")
        dates = find_available_dates(config)
        if not dates:
            print("No data available to backfill.")
            return

        # Skip dates already in the database
        existing = {row["date"] for row in conn.execute("SELECT date FROM daily_summary").fetchall()}
        to_collect = [d for d in dates if d not in existing]

        print(f"Found {len(dates)} dates with data, {len(to_collect)} new to collect.")
        for i, date_str in enumerate(to_collect):
            print(f"  [{i+1}/{len(to_collect)}] Collecting {date_str}...", end=" ", flush=True)
            if collect_day(date_str, config, conn):
                print("ok")
            else:
                print("no data")
            time.sleep(0.5)  # Be gentle with APIs

        print(f"Backfill complete. {len(to_collect)} days collected.")

    else:
        # Default: collect the most recent day not yet in the database
        print("Finding latest available data...")
        for days_ago in range(1, 6):
            day = datetime.now(timezone.utc) - timedelta(days=days_ago)
            date_str = day.strftime("%Y-%m-%d")
            existing = conn.execute("SELECT 1 FROM daily_summary WHERE date = ?", (date_str,)).fetchone()
            if existing:
                print(f"  {date_str} already collected, skipping.")
                continue
            print(f"  Collecting {date_str}...", end=" ", flush=True)
            if collect_day(date_str, config, conn):
                print("ok")
                break
            else:
                print("no data yet")
        else:
            print("No new data to collect.")

    conn.close()


if __name__ == "__main__":
    main()
