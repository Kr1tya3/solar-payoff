"""Tests for solar-payoff application."""

import sqlite3
from unittest.mock import MagicMock, patch

import pytest

import db
import octopus
import solis
from collect import is_night


# --- Fixtures ---


@pytest.fixture
def in_memory_db():
    """Create an in-memory SQLite database with schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE daily_summary (
            date TEXT PRIMARY KEY, import_kwh REAL, export_kwh REAL,
            generation_kwh REAL, self_consumption_kwh REAL,
            day_import_kwh REAL, night_import_kwh REAL,
            import_cost_pence REAL, day_cost_pence REAL, night_cost_pence REAL,
            standing_charge_pence REAL, export_earnings_pence REAL,
            solar_savings_pence REAL, import_day_rate REAL,
            import_night_rate REAL, export_rate REAL
        );
        CREATE TABLE half_hourly (
            date TEXT, interval_start TEXT, import_kwh REAL,
            export_kwh REAL, is_night INTEGER, rate_p_kwh REAL,
            PRIMARY KEY (date, interval_start)
        );
        CREATE TABLE solar_5min (
            date TEXT, time_str TEXT, pac_watts REAL, e_today_kwh REAL,
            PRIMARY KEY (date, time_str)
        );
    """)
    yield conn
    conn.close()


@pytest.fixture
def sample_daily_summary():
    return {
        "date": "2026-03-04",
        "import_kwh": 6.075, "export_kwh": 7.966,
        "generation_kwh": 11.9, "self_consumption_kwh": 3.934,
        "day_import_kwh": 3.5, "night_import_kwh": 2.575,
        "import_cost_pence": 162.87, "day_cost_pence": 124.22,
        "night_cost_pence": 38.65, "standing_charge_pence": 47.76,
        "export_earnings_pence": 95.59, "solar_savings_pence": 139.58,
        "import_day_rate": 35.49, "import_night_rate": 15.02,
        "export_rate": 12.0,
    }


@pytest.fixture
def sample_import_data():
    """Half-hourly import data for a day with known totals."""
    return [
        {"consumption": 0.15, "interval_start": "2026-03-04T00:00:00Z", "interval_end": "2026-03-04T00:30:00Z"},
        {"consumption": 0.15, "interval_start": "2026-03-04T00:30:00Z", "interval_end": "2026-03-04T01:00:00Z"},
        {"consumption": 0.20, "interval_start": "2026-03-04T03:00:00Z", "interval_end": "2026-03-04T03:30:00Z"},
        {"consumption": 0.10, "interval_start": "2026-03-04T07:30:00Z", "interval_end": "2026-03-04T08:00:00Z"},
        {"consumption": 0.30, "interval_start": "2026-03-04T12:00:00Z", "interval_end": "2026-03-04T12:30:00Z"},
        {"consumption": 0.50, "interval_start": "2026-03-04T18:00:00Z", "interval_end": "2026-03-04T18:30:00Z"},
    ]


@pytest.fixture
def sample_export_data():
    return [
        {"consumption": 0.0, "interval_start": "2026-03-04T00:00:00Z", "interval_end": "2026-03-04T00:30:00Z"},
        {"consumption": 0.0, "interval_start": "2026-03-04T00:30:00Z", "interval_end": "2026-03-04T01:00:00Z"},
        {"consumption": 0.0, "interval_start": "2026-03-04T03:00:00Z", "interval_end": "2026-03-04T03:30:00Z"},
        {"consumption": 0.0, "interval_start": "2026-03-04T07:30:00Z", "interval_end": "2026-03-04T08:00:00Z"},
        {"consumption": 0.80, "interval_start": "2026-03-04T12:00:00Z", "interval_end": "2026-03-04T12:30:00Z"},
        {"consumption": 0.20, "interval_start": "2026-03-04T18:00:00Z", "interval_end": "2026-03-04T18:30:00Z"},
    ]


SAMPLE_ACCOUNT = {
    "number": "A-TEST1234",
    "properties": [{
        "electricity_meter_points": [
            {
                "mpan": "1900092329384",
                "is_export": True,
                "agreements": [
                    {"tariff_code": "E-1R-OUTGOING-FIX-12M-19-05-13-J",
                     "valid_from": "2024-01-26T00:00:00Z", "valid_to": "2025-01-26T00:00:00Z"},
                    {"tariff_code": "E-1R-OUTGOING-VAR-24-10-26-J",
                     "valid_from": "2025-01-26T00:00:00Z", "valid_to": None},
                ],
            },
            {
                "mpan": "1900002240580",
                "is_export": False,
                "agreements": [
                    {"tariff_code": "E-2R-VAR-22-11-01-J",
                     "valid_from": "2024-01-01T00:00:00Z", "valid_to": None},
                ],
            },
        ],
    }],
}


# --- octopus.py tests ---


class TestExtractProductCode:
    def test_standard_tariff(self):
        assert octopus._extract_product_code("E-2R-VAR-22-11-01-J") == "VAR-22-11-01"

    def test_export_tariff(self):
        assert octopus._extract_product_code("E-1R-OUTGOING-VAR-24-10-26-J") == "OUTGOING-VAR-24-10-26"

    def test_fixed_tariff(self):
        assert octopus._extract_product_code("E-1R-OUTGOING-FIX-12M-19-05-13-J") == "OUTGOING-FIX-12M-19-05-13"

    def test_single_region_letter(self):
        assert octopus._extract_product_code("E-1R-AGILE-FLEX-22-11-25-C") == "AGILE-FLEX-22-11-25"


class TestGetActiveTariffs:
    @patch("octopus.fetch_account")
    def test_finds_current_import_and_export(self, mock_fetch):
        mock_fetch.return_value = SAMPLE_ACCOUNT
        result = octopus.get_active_tariffs("key", "A-TEST", "2026-03-04")

        assert result["import"]["tariff_code"] == "E-2R-VAR-22-11-01-J"
        assert result["import"]["is_economy7"] is True
        assert result["import"]["product_code"] == "VAR-22-11-01"

        assert result["export"]["tariff_code"] == "E-1R-OUTGOING-VAR-24-10-26-J"
        assert result["export"]["is_economy7"] is False

    @patch("octopus.fetch_account")
    def test_respects_valid_to_date(self, mock_fetch):
        mock_fetch.return_value = SAMPLE_ACCOUNT
        # Date within the old fixed export tariff period
        result = octopus.get_active_tariffs("key", "A-TEST", "2024-06-15")
        assert result["export"]["tariff_code"] == "E-1R-OUTGOING-FIX-12M-19-05-13-J"

    @patch("octopus.fetch_account")
    def test_returns_none_when_no_match(self, mock_fetch):
        mock_fetch.return_value = {"properties": [{"electricity_meter_points": []}]}
        result = octopus.get_active_tariffs("key", "A-TEST", "2026-03-04")
        assert result["import"] is None
        assert result["export"] is None


class TestFetchConsumption:
    @patch("octopus.requests.get")
    def test_single_page(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "results": [{"consumption": 0.5, "interval_start": "2026-03-04T00:00:00Z"}],
            "next": None,
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = octopus.fetch_consumption("key", "mpan", "serial", "2026-03-04T00:00Z", "2026-03-05T00:00Z")
        assert len(result) == 1
        assert result[0]["consumption"] == 0.5

    @patch("octopus.requests.get")
    def test_pagination(self, mock_get):
        page1 = MagicMock()
        page1.json.return_value = {
            "results": [{"consumption": 0.5}],
            "next": "https://api.octopus.energy/v1/page2",
        }
        page1.raise_for_status = MagicMock()

        page2 = MagicMock()
        page2.json.return_value = {
            "results": [{"consumption": 0.3}],
            "next": None,
        }
        page2.raise_for_status = MagicMock()

        mock_get.side_effect = [page1, page2]

        result = octopus.fetch_consumption("key", "mpan", "serial", "from", "to")
        assert len(result) == 2
        assert result[0]["consumption"] == 0.5
        assert result[1]["consumption"] == 0.3


# --- solis.py tests ---


class TestSolisAuthHeaders:
    def test_headers_structure(self):
        headers = solis._auth_headers("test_id", "test_secret", '{"sn":"123"}', "/v1/api/inverterDay")

        assert "Content-MD5" in headers
        assert headers["Content-Type"] == "application/json"
        assert "Date" in headers
        assert headers["Authorization"].startswith("API test_id:")

    def test_content_md5_is_correct(self):
        import base64
        import hashlib

        body = '{"sn":"123"}'
        headers = solis._auth_headers("id", "secret", body, "/v1/api/test")

        expected_md5 = base64.b64encode(hashlib.md5(body.encode("utf-8")).digest()).decode("utf-8")
        assert headers["Content-MD5"] == expected_md5

    def test_date_contains_gmt(self):
        headers = solis._auth_headers("id", "secret", "{}", "/v1/api/test")
        assert "GMT" in headers["Date"]

    def test_different_secrets_produce_different_signatures(self):
        h1 = solis._auth_headers("id", "secret1", "{}", "/v1/api/test")
        h2 = solis._auth_headers("id", "secret2", "{}", "/v1/api/test")
        sig1 = h1["Authorization"].split(":")[1]
        sig2 = h2["Authorization"].split(":")[1]
        assert sig1 != sig2


class TestSolisApiRequest:
    @patch("solis.requests.post")
    def test_successful_request(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"success": True, "code": "0", "data": [{"pac": 100}]}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        result = solis.api_request("id", "secret", "/v1/api/test", {"key": "val"})
        assert result["success"] is True

    @patch("solis.requests.post")
    def test_api_error_raises(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"success": False, "code": "1", "msg": "wrong sign"}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        with pytest.raises(RuntimeError, match="wrong sign"):
            solis.api_request("id", "secret", "/v1/api/test", {})


# --- collect.py tests ---


class TestIsNight:
    def test_midnight_is_night(self):
        # 00:30 is within 00:30-07:30
        assert is_night("2026-03-04T00:30:00Z") is True

    def test_early_morning_is_night(self):
        assert is_night("2026-03-04T03:00:00Z") is True

    def test_before_night_start(self):
        # 00:00 is before 00:30
        assert is_night("2026-03-04T00:00:00Z") is False

    def test_night_end_boundary(self):
        # 07:30 is NOT night (end is exclusive)
        assert is_night("2026-03-04T07:30:00Z") is False

    def test_midday_is_not_night(self):
        assert is_night("2026-03-04T12:00:00Z") is False

    def test_evening_is_not_night(self):
        assert is_night("2026-03-04T20:00:00Z") is False

    def test_just_before_night_end(self):
        assert is_night("2026-03-04T07:00:00Z") is True


# --- db.py tests ---


class TestDatabase:
    def test_upsert_and_get_daily_summary(self, in_memory_db, sample_daily_summary):
        db.upsert_daily_summary(in_memory_db, sample_daily_summary)
        in_memory_db.commit()

        rows = db.get_daily_summaries(in_memory_db)
        assert len(rows) == 1
        assert rows[0]["date"] == "2026-03-04"
        assert rows[0]["import_kwh"] == 6.075
        assert rows[0]["generation_kwh"] == 11.9

    def test_upsert_replaces_existing(self, in_memory_db, sample_daily_summary):
        db.upsert_daily_summary(in_memory_db, sample_daily_summary)
        # Update the generation value
        sample_daily_summary["generation_kwh"] = 15.0
        db.upsert_daily_summary(in_memory_db, sample_daily_summary)
        in_memory_db.commit()

        rows = db.get_daily_summaries(in_memory_db)
        assert len(rows) == 1
        assert rows[0]["generation_kwh"] == 15.0

    def test_date_range_filtering(self, in_memory_db, sample_daily_summary):
        for date in ["2026-03-01", "2026-03-02", "2026-03-03", "2026-03-04"]:
            sample_daily_summary["date"] = date
            db.upsert_daily_summary(in_memory_db, sample_daily_summary)
        in_memory_db.commit()

        rows = db.get_daily_summaries(in_memory_db, date_from="2026-03-02", date_to="2026-03-03")
        assert len(rows) == 2
        assert rows[0]["date"] == "2026-03-02"
        assert rows[1]["date"] == "2026-03-03"

    def test_date_range_from_only(self, in_memory_db, sample_daily_summary):
        for date in ["2026-03-01", "2026-03-02", "2026-03-03"]:
            sample_daily_summary["date"] = date
            db.upsert_daily_summary(in_memory_db, sample_daily_summary)
        in_memory_db.commit()

        rows = db.get_daily_summaries(in_memory_db, date_from="2026-03-02")
        assert len(rows) == 2

    def test_half_hourly_upsert_and_get(self, in_memory_db):
        rows = [
            {"date": "2026-03-04", "interval_start": "2026-03-04T00:00:00Z",
             "import_kwh": 0.15, "export_kwh": 0.0, "is_night": 0, "rate_p_kwh": 35.49},
            {"date": "2026-03-04", "interval_start": "2026-03-04T00:30:00Z",
             "import_kwh": 0.10, "export_kwh": 0.0, "is_night": 1, "rate_p_kwh": 15.02},
        ]
        db.upsert_half_hourly(in_memory_db, rows)
        in_memory_db.commit()

        result = db.get_half_hourly(in_memory_db, "2026-03-04")
        assert len(result) == 2
        assert result[0]["import_kwh"] == 0.15
        assert result[1]["is_night"] == 1

    def test_half_hourly_returns_empty_for_missing_date(self, in_memory_db):
        assert db.get_half_hourly(in_memory_db, "2099-01-01") == []

    def test_solar_5min_upsert_and_get(self, in_memory_db):
        rows = [
            {"date": "2026-03-04", "time_str": "08:00:00", "pac_watts": 500, "e_today_kwh": 0.5},
            {"date": "2026-03-04", "time_str": "08:05:00", "pac_watts": 520, "e_today_kwh": 0.55},
        ]
        db.upsert_solar_5min(in_memory_db, rows)
        in_memory_db.commit()

        result = db.get_solar_5min(in_memory_db, "2026-03-04")
        assert len(result) == 2
        assert result[0]["pac_watts"] == 500

    def test_get_date_range(self, in_memory_db, sample_daily_summary):
        for date in ["2026-03-01", "2026-03-04"]:
            sample_daily_summary["date"] = date
            db.upsert_daily_summary(in_memory_db, sample_daily_summary)
        in_memory_db.commit()

        earliest, latest = db.get_date_range(in_memory_db)
        assert earliest == "2026-03-01"
        assert latest == "2026-03-04"

    def test_get_date_range_empty(self, in_memory_db):
        earliest, latest = db.get_date_range(in_memory_db)
        assert earliest is None
        assert latest is None


# --- Cost calculation tests (collect.py logic) ---


class TestCostCalculation:
    """Test the cost calculation logic from collect.collect_day, extracted inline."""

    def test_economy7_cost_split(self, sample_import_data):
        """Night periods get night rate, day periods get day rate."""
        day_rate = 35.49
        night_rate = 15.02

        day_kwh = night_kwh = day_cost = night_cost = 0.0
        for r in sample_import_data:
            kwh = r["consumption"]
            if is_night(r["interval_start"]):
                night_kwh += kwh
                night_cost += kwh * night_rate
            else:
                day_kwh += kwh
                day_cost += kwh * day_rate

        # Night periods: 00:30 (0.15) + 03:00 (0.20) = 0.35 kWh
        assert night_kwh == pytest.approx(0.35)
        # Day periods: 00:00 (0.15) + 07:30 (0.10) + 12:00 (0.30) + 18:00 (0.50) = 1.05 kWh
        assert day_kwh == pytest.approx(1.05)

        assert night_cost == pytest.approx(0.35 * 15.02)
        assert day_cost == pytest.approx(1.05 * 35.49)

    def test_self_consumption_calculation(self):
        """Self-consumption = generation - export."""
        solar_gen = 11.9
        total_export = 7.966
        self_consumption = solar_gen - total_export
        assert self_consumption == pytest.approx(3.934)

    def test_solar_savings_uses_day_rate(self):
        """Solar savings should use day rate since generation happens during daytime."""
        self_consumption = 3.934
        day_rate = 35.49
        savings = self_consumption * day_rate
        assert savings == pytest.approx(139.58, abs=0.1)

    def test_export_earnings(self):
        total_export = 7.966
        export_rate = 12.0
        earnings = total_export * export_rate
        assert earnings == pytest.approx(95.59, abs=0.01)

    def test_total_benefit(self):
        solar_savings = 139.58
        export_earnings = 95.59
        total = solar_savings + export_earnings
        assert total == pytest.approx(235.17, abs=0.1)

    def test_net_cost(self):
        import_cost = 162.87
        standing_charge = 47.76
        export_earnings = 95.59
        net = import_cost + standing_charge - export_earnings
        assert net == pytest.approx(115.04, abs=0.1)


# --- Dashboard HTML generation tests ---


class TestDashboardGeneration:
    def test_generates_valid_html(self):
        from dashboard import generate_html

        daily = [{
            "date": "2026-03-04", "import_kwh": 6.0, "export_kwh": 8.0,
            "generation_kwh": 12.0, "self_consumption_kwh": 4.0,
            "day_import_kwh": 3.5, "night_import_kwh": 2.5,
            "import_cost_pence": 160.0, "day_cost_pence": 120.0,
            "night_cost_pence": 40.0, "standing_charge_pence": 47.0,
            "export_earnings_pence": 96.0, "solar_savings_pence": 140.0,
            "import_day_rate": 35.49, "import_night_rate": 15.02,
            "export_rate": 12.0,
        }]
        detail = {"2026-03-04": [{"interval_start": "2026-03-04T00:00:00Z",
                                   "import_kwh": 0.1, "export_kwh": 0.0,
                                   "is_night": 0, "rate_p_kwh": 35.49}]}
        solar = {"2026-03-04": [{"time_str": "08:00:00", "pac_watts": 500, "e_today_kwh": 0.5}]}

        html = generate_html(daily, detail, solar)

        assert html.startswith("<!DOCTYPE html>")
        assert "Solar Energy Dashboard" in html
        assert "2026-03-04" in html
        assert "chart.js" in html.lower() or "Chart" in html

    def test_handles_multiple_days(self):
        from dashboard import generate_html

        base = {
            "import_kwh": 5.0, "export_kwh": 6.0,
            "generation_kwh": 10.0, "self_consumption_kwh": 4.0,
            "day_import_kwh": 3.0, "night_import_kwh": 2.0,
            "import_cost_pence": 100.0, "day_cost_pence": 80.0,
            "night_cost_pence": 20.0, "standing_charge_pence": 47.0,
            "export_earnings_pence": 72.0, "solar_savings_pence": 120.0,
            "import_day_rate": 35.49, "import_night_rate": 15.02,
            "export_rate": 12.0,
        }
        daily = [{**base, "date": f"2026-03-0{i}"} for i in range(1, 4)]

        html = generate_html(daily, {}, {})
        assert "2026-03-01" in html
        assert "2026-03-03" in html

    def test_handles_empty_detail_data(self):
        from dashboard import generate_html

        daily = [{
            "date": "2026-03-04", "import_kwh": 0, "export_kwh": 0,
            "generation_kwh": 0, "self_consumption_kwh": 0,
            "day_import_kwh": 0, "night_import_kwh": 0,
            "import_cost_pence": 0, "day_cost_pence": 0,
            "night_cost_pence": 0, "standing_charge_pence": 0,
            "export_earnings_pence": 0, "solar_savings_pence": 0,
            "import_day_rate": 0, "import_night_rate": 0, "export_rate": 0,
        }]

        html = generate_html(daily, {}, {})
        assert "<!DOCTYPE html>" in html
