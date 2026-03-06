"""SQLite database for storing historical energy data."""

import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "solar.db")


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(db_path: str = DB_PATH):
    """Create tables if they don't exist."""
    conn = get_connection(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS daily_summary (
            date TEXT PRIMARY KEY,
            import_kwh REAL,
            export_kwh REAL,
            generation_kwh REAL,
            self_consumption_kwh REAL,
            day_import_kwh REAL,
            night_import_kwh REAL,
            import_cost_pence REAL,
            day_cost_pence REAL,
            night_cost_pence REAL,
            standing_charge_pence REAL,
            export_earnings_pence REAL,
            solar_savings_pence REAL,
            import_day_rate REAL,
            import_night_rate REAL,
            export_rate REAL
        );

        CREATE TABLE IF NOT EXISTS half_hourly (
            date TEXT,
            interval_start TEXT,
            import_kwh REAL,
            export_kwh REAL,
            is_night INTEGER,
            rate_p_kwh REAL,
            PRIMARY KEY (date, interval_start)
        );

        CREATE TABLE IF NOT EXISTS solar_5min (
            date TEXT,
            time_str TEXT,
            pac_watts REAL,
            e_today_kwh REAL,
            PRIMARY KEY (date, time_str)
        );
    """)
    conn.commit()
    conn.close()


def upsert_daily_summary(conn: sqlite3.Connection, data: dict):
    """Insert or replace a daily summary row."""
    conn.execute("""
        INSERT OR REPLACE INTO daily_summary (
            date, import_kwh, export_kwh, generation_kwh, self_consumption_kwh,
            day_import_kwh, night_import_kwh, import_cost_pence, day_cost_pence,
            night_cost_pence, standing_charge_pence, export_earnings_pence,
            solar_savings_pence, import_day_rate, import_night_rate, export_rate
        ) VALUES (
            :date, :import_kwh, :export_kwh, :generation_kwh, :self_consumption_kwh,
            :day_import_kwh, :night_import_kwh, :import_cost_pence, :day_cost_pence,
            :night_cost_pence, :standing_charge_pence, :export_earnings_pence,
            :solar_savings_pence, :import_day_rate, :import_night_rate, :export_rate
        )
    """, data)


def upsert_half_hourly(conn: sqlite3.Connection, rows: list[dict]):
    """Insert or replace half-hourly rows."""
    conn.executemany("""
        INSERT OR REPLACE INTO half_hourly (date, interval_start, import_kwh, export_kwh, is_night, rate_p_kwh)
        VALUES (:date, :interval_start, :import_kwh, :export_kwh, :is_night, :rate_p_kwh)
    """, rows)


def upsert_solar_5min(conn: sqlite3.Connection, rows: list[dict]):
    """Insert or replace solar 5-min rows."""
    conn.executemany("""
        INSERT OR REPLACE INTO solar_5min (date, time_str, pac_watts, e_today_kwh)
        VALUES (:date, :time_str, :pac_watts, :e_today_kwh)
    """, rows)


def get_daily_summaries(conn: sqlite3.Connection, date_from: str = None, date_to: str = None) -> list[dict]:
    """Fetch daily summaries, optionally filtered by date range."""
    query = "SELECT * FROM daily_summary"
    params = []
    conditions = []
    if date_from:
        conditions.append("date >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("date <= ?")
        params.append(date_to)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY date"
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def get_half_hourly(conn: sqlite3.Connection, date: str) -> list[dict]:
    """Fetch half-hourly data for a specific date."""
    return [dict(row) for row in conn.execute(
        "SELECT * FROM half_hourly WHERE date = ? ORDER BY interval_start", (date,)
    ).fetchall()]


def get_solar_5min(conn: sqlite3.Connection, date: str) -> list[dict]:
    """Fetch solar 5-min data for a specific date."""
    return [dict(row) for row in conn.execute(
        "SELECT * FROM solar_5min WHERE date = ? ORDER BY time_str", (date,)
    ).fetchall()]


def get_date_range(conn: sqlite3.Connection) -> tuple[str | None, str | None]:
    """Get the earliest and latest dates in the database."""
    row = conn.execute("SELECT MIN(date), MAX(date) FROM daily_summary").fetchone()
    return (row[0], row[1]) if row else (None, None)
