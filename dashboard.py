"""Generate a solar energy dashboard with cost/savings calculations."""

import os
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

import octopus
import solis

load_dotenv()

# Economy 7 off-peak hours (UTC). Typical for South East England: 00:30-07:30.
# Configurable via env vars.
NIGHT_START_HOUR = float(os.getenv("ECONOMY7_NIGHT_START", "0.5"))  # 00:30
NIGHT_END_HOUR = float(os.getenv("ECONOMY7_NIGHT_END", "7.5"))  # 07:30


def get_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        print(f"Error: {name} not set. See .env.example")
        sys.exit(1)
    return value


def is_night_period(interval_start: str) -> bool:
    """Check if a half-hour period falls within Economy 7 off-peak hours (UTC)."""
    dt = datetime.fromisoformat(interval_start.replace("Z", "+00:00"))
    hour = dt.hour + dt.minute / 60.0
    return NIGHT_START_HOUR <= hour < NIGHT_END_HOUR


def calculate_costs(
    import_data: list[dict],
    export_data: list[dict],
    solar_generation_kwh: float,
    import_rates: dict,
    export_rate: float,
) -> dict:
    """Calculate energy costs and solar savings.

    All monetary values in pence.
    """
    total_import_kwh = sum(r["consumption"] for r in import_data)
    total_export_kwh = sum(r["consumption"] for r in export_data)
    self_consumption_kwh = solar_generation_kwh - total_export_kwh

    # Import cost by time-of-use
    if "day_rate" in import_rates:
        # Economy 7
        day_cost = 0.0
        night_cost = 0.0
        day_kwh = 0.0
        night_kwh = 0.0
        for r in import_data:
            kwh = r["consumption"]
            if is_night_period(r["interval_start"]):
                night_cost += kwh * import_rates["night_rate"]
                night_kwh += kwh
            else:
                day_cost += kwh * import_rates["day_rate"]
                day_kwh += kwh
        import_cost = day_cost + night_cost
    else:
        # Standard single rate
        import_cost = total_import_kwh * import_rates.get("unit_rate", 0)
        day_kwh = total_import_kwh
        night_kwh = 0
        day_cost = import_cost
        night_cost = 0

    standing_charge = import_rates.get("standing_charge", 0)

    # Export earnings
    export_earnings = total_export_kwh * export_rate

    # Solar savings = what you would have paid to import the self-consumed energy.
    # Self-consumption happens during daylight hours, so use the day rate.
    day_rate = import_rates.get("day_rate", import_rates.get("unit_rate", 0))
    solar_savings = self_consumption_kwh * day_rate

    return {
        "total_import_kwh": total_import_kwh,
        "total_export_kwh": total_export_kwh,
        "solar_generation_kwh": solar_generation_kwh,
        "self_consumption_kwh": self_consumption_kwh,
        "day_import_kwh": day_kwh,
        "night_import_kwh": night_kwh,
        "import_cost_pence": import_cost,
        "day_cost_pence": day_cost,
        "night_cost_pence": night_cost,
        "standing_charge_pence": standing_charge,
        "total_cost_pence": import_cost + standing_charge,
        "export_earnings_pence": export_earnings,
        "solar_savings_pence": solar_savings,
        "net_cost_pence": import_cost + standing_charge - export_earnings,
        "import_rates": import_rates,
        "export_rate": export_rate,
    }


def build_half_hourly_data(import_data: list[dict], export_data: list[dict], import_rates: dict) -> list[dict]:
    """Build aligned half-hourly data for charting."""
    export_by_period = {r["interval_start"]: r["consumption"] for r in export_data}
    rows = []
    for r in import_data:
        start = r["interval_start"]
        dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        time_label = dt.strftime("%H:%M")
        imp = r["consumption"]
        exp = export_by_period.get(start, 0)
        night = is_night_period(start)
        if "day_rate" in import_rates:
            rate = import_rates["night_rate"] if night else import_rates["day_rate"]
        else:
            rate = import_rates.get("unit_rate", 0)
        rows.append({
            "time": time_label,
            "import_kwh": round(imp, 3),
            "export_kwh": round(exp, 3),
            "is_night": night,
            "rate_p_kwh": rate,
            "import_cost_p": round(imp * rate, 2),
        })
    return rows


def generate_html(date_str: str, costs: dict, half_hourly: list[dict], solar_points: list[dict]) -> str:
    """Generate the dashboard HTML."""
    import json

    # Prepare solar generation chart data (5-min intervals)
    solar_times = []
    solar_power = []
    for p in solar_points:
        time_str = p.get("time", p.get("timeStr", ""))
        if ":" in time_str:
            # Use just HH:MM
            parts = time_str.split(":")
            solar_times.append(f"{parts[0]}:{parts[1]}")
        solar_power.append(p.get("pac", 0))

    # Half-hourly chart data
    hh_times = [r["time"] for r in half_hourly]
    hh_import = [r["import_kwh"] for r in half_hourly]
    hh_export = [r["export_kwh"] for r in half_hourly]
    hh_night = [r["is_night"] for r in half_hourly]

    c = costs
    gen = c["solar_generation_kwh"]
    self_pct = (c["self_consumption_kwh"] / gen * 100) if gen > 0 else 0

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Solar Dashboard - {date_str}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  :root {{
    --bg: #0f172a; --card: #1e293b; --border: #334155;
    --text: #e2e8f0; --muted: #94a3b8;
    --green: #22c55e; --yellow: #eab308; --blue: #3b82f6;
    --red: #ef4444; --purple: #a855f7;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: var(--bg); color: var(--text); padding: 1.5rem; }}
  h1 {{ font-size: 1.5rem; margin-bottom: 0.25rem; }}
  .date {{ color: var(--muted); margin-bottom: 1.5rem; font-size: 0.9rem; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }}
  .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 0.75rem; padding: 1.25rem; }}
  .card-label {{ font-size: 0.8rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.5rem; }}
  .card-value {{ font-size: 1.75rem; font-weight: 700; }}
  .card-sub {{ font-size: 0.8rem; color: var(--muted); margin-top: 0.25rem; }}
  .green {{ color: var(--green); }}
  .yellow {{ color: var(--yellow); }}
  .blue {{ color: var(--blue); }}
  .red {{ color: var(--red); }}
  .purple {{ color: var(--purple); }}
  .chart-container {{ background: var(--card); border: 1px solid var(--border); border-radius: 0.75rem; padding: 1.25rem; margin-bottom: 1.5rem; }}
  .chart-title {{ font-size: 1rem; font-weight: 600; margin-bottom: 1rem; }}
  .chart-wrap {{ position: relative; height: 300px; }}
  .rate-info {{ display: flex; gap: 1.5rem; flex-wrap: wrap; margin-bottom: 1.5rem; }}
  .rate-badge {{ background: var(--card); border: 1px solid var(--border); border-radius: 0.5rem; padding: 0.5rem 1rem; font-size: 0.85rem; }}
  .rate-badge span {{ font-weight: 600; }}
</style>
</head>
<body>

<h1>Solar Energy Dashboard</h1>
<p class="date">{date_str}</p>

<div class="rate-info">
  <div class="rate-badge">Day rate: <span>{c['import_rates'].get('day_rate', c['import_rates'].get('unit_rate', 0)):.2f}p/kWh</span></div>
  <div class="rate-badge">Night rate: <span>{c['import_rates'].get('night_rate', '-')}{"p/kWh" if 'night_rate' in c['import_rates'] else ''}</span></div>
  <div class="rate-badge">Export rate: <span>{c['export_rate']:.2f}p/kWh</span></div>
  <div class="rate-badge">Standing charge: <span>{c['standing_charge_pence']:.2f}p/day</span></div>
</div>

<div class="grid">
  <div class="card">
    <div class="card-label">Solar Generated</div>
    <div class="card-value yellow">{gen:.1f} kWh</div>
    <div class="card-sub">Self-consumed: {c['self_consumption_kwh']:.1f} kWh ({self_pct:.0f}%)</div>
  </div>
  <div class="card">
    <div class="card-label">Grid Import</div>
    <div class="card-value red">{c['total_import_kwh']:.1f} kWh</div>
    <div class="card-sub">Day: {c['day_import_kwh']:.1f} / Night: {c['night_import_kwh']:.1f} kWh</div>
  </div>
  <div class="card">
    <div class="card-label">Grid Export</div>
    <div class="card-value blue">{c['total_export_kwh']:.1f} kWh</div>
    <div class="card-sub">Exported surplus solar</div>
  </div>
  <div class="card">
    <div class="card-label">Import Cost</div>
    <div class="card-value red">&pound;{c['total_cost_pence'] / 100:.2f}</div>
    <div class="card-sub">Energy: &pound;{c['import_cost_pence'] / 100:.2f} + Standing: &pound;{c['standing_charge_pence'] / 100:.2f}</div>
  </div>
  <div class="card">
    <div class="card-label">Export Earnings</div>
    <div class="card-value green">&pound;{c['export_earnings_pence'] / 100:.2f}</div>
    <div class="card-sub">{c['total_export_kwh']:.1f} kWh @ {c['export_rate']:.1f}p</div>
  </div>
  <div class="card">
    <div class="card-label">Solar Savings</div>
    <div class="card-value green">&pound;{c['solar_savings_pence'] / 100:.2f}</div>
    <div class="card-sub">Avoided import cost from self-use</div>
  </div>
  <div class="card">
    <div class="card-label">Net Cost</div>
    <div class="card-value purple">&pound;{c['net_cost_pence'] / 100:.2f}</div>
    <div class="card-sub">Import + standing - export</div>
  </div>
  <div class="card">
    <div class="card-label">Total Solar Benefit</div>
    <div class="card-value green">&pound;{(c['solar_savings_pence'] + c['export_earnings_pence']) / 100:.2f}</div>
    <div class="card-sub">Savings + export earnings</div>
  </div>
</div>

<div class="chart-container">
  <div class="chart-title">Solar Generation (5-min intervals)</div>
  <div class="chart-wrap"><canvas id="solarChart"></canvas></div>
</div>

<div class="chart-container">
  <div class="chart-title">Grid Import / Export (half-hourly)</div>
  <div class="chart-wrap"><canvas id="gridChart"></canvas></div>
</div>

<div class="chart-container">
  <div class="chart-title">Energy Flow Summary</div>
  <div class="chart-wrap" style="height:250px"><canvas id="flowChart"></canvas></div>
</div>

<script>
const solarTimes = {json.dumps(solar_times)};
const solarPower = {json.dumps(solar_power)};
const hhTimes = {json.dumps(hh_times)};
const hhImport = {json.dumps(hh_import)};
const hhExport = {json.dumps(hh_export)};
const hhNight = {json.dumps(hh_night)};

Chart.defaults.color = '#94a3b8';
Chart.defaults.borderColor = '#334155';

// Solar generation chart
new Chart(document.getElementById('solarChart'), {{
  type: 'line',
  data: {{
    labels: solarTimes,
    datasets: [{{
      label: 'Solar Power (W)',
      data: solarPower,
      borderColor: '#eab308',
      backgroundColor: 'rgba(234,179,8,0.1)',
      fill: true,
      pointRadius: 0,
      borderWidth: 2,
      tension: 0.3,
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    scales: {{
      x: {{ ticks: {{ maxTicksLimit: 24, maxRotation: 0 }} }},
      y: {{ beginAtZero: true, title: {{ display: true, text: 'Watts' }} }}
    }},
    plugins: {{ legend: {{ display: false }} }}
  }}
}});

// Grid import/export chart
const nightBg = hhNight.map(n => n ? 'rgba(59,130,246,0.8)' : 'rgba(239,68,68,0.8)');
new Chart(document.getElementById('gridChart'), {{
  type: 'bar',
  data: {{
    labels: hhTimes,
    datasets: [
      {{
        label: 'Import (kWh)',
        data: hhImport,
        backgroundColor: nightBg,
      }},
      {{
        label: 'Export (kWh)',
        data: hhExport.map(v => -v),
        backgroundColor: 'rgba(34,197,94,0.8)',
      }}
    ]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    scales: {{
      x: {{ stacked: true, ticks: {{ maxRotation: 0 }} }},
      y: {{ stacked: true, title: {{ display: true, text: 'kWh' }} }}
    }},
    plugins: {{
      tooltip: {{
        callbacks: {{
          label: function(ctx) {{
            const val = Math.abs(ctx.raw);
            return ctx.dataset.label + ': ' + val.toFixed(3) + ' kWh';
          }}
        }}
      }}
    }}
  }}
}});

// Energy flow summary (doughnut)
new Chart(document.getElementById('flowChart'), {{
  type: 'doughnut',
  data: {{
    labels: ['Self-consumed', 'Exported', 'Grid Import (Day)', 'Grid Import (Night)'],
    datasets: [{{
      data: [{c['self_consumption_kwh']:.2f}, {c['total_export_kwh']:.2f}, {c['day_import_kwh']:.2f}, {c['night_import_kwh']:.2f}],
      backgroundColor: ['#eab308', '#22c55e', '#ef4444', '#3b82f6'],
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{
      legend: {{ position: 'right' }},
      tooltip: {{
        callbacks: {{
          label: function(ctx) {{
            return ctx.label + ': ' + ctx.raw.toFixed(1) + ' kWh';
          }}
        }}
      }}
    }}
  }}
}});
</script>
</body>
</html>"""


def find_latest_date(api_key: str, mpan: str, serial: str) -> str | None:
    """Find the most recent date with available Octopus data (up to 5 days back)."""
    for days_ago in range(1, 6):
        day = datetime.now(timezone.utc) - timedelta(days=days_ago)
        date_str = day.strftime("%Y-%m-%d")
        period_from = f"{date_str}T00:00:00Z"
        period_to = (day + timedelta(days=1)).strftime("%Y-%m-%d") + "T00:00:00Z"
        data = octopus.fetch_consumption(api_key, mpan, serial, period_from, period_to)
        if data:
            return date_str
    return None


def main():
    # Load config
    api_key = get_env("OCTOPUS_API_KEY")
    account = get_env("OCTOPUS_ACCOUNT_NUMBER")
    import_mpan = get_env("OCTOPUS_IMPORT_MPAN")
    import_serial = get_env("OCTOPUS_IMPORT_SERIAL")
    export_mpan = get_env("OCTOPUS_EXPORT_MPAN")
    export_serial = get_env("OCTOPUS_EXPORT_SERIAL")
    solis_id = get_env("SOLIS_API_ID")
    solis_secret = get_env("SOLIS_API_SECRET")
    solis_sn = get_env("SOLIS_INVERTER_SN")
    solis_tz = int(os.getenv("SOLIS_TIMEZONE", "0"))

    # Find latest available date
    print("Finding latest available data...")
    date_str = find_latest_date(api_key, import_mpan, import_serial)
    if not date_str:
        print("No Octopus data found in the last 5 days.")
        sys.exit(1)

    period_from = f"{date_str}T00:00:00Z"
    next_day = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    period_to = f"{next_day}T00:00:00Z"
    print(f"Using date: {date_str}")

    # Fetch consumption data
    print("Fetching import/export data...")
    import_data = octopus.fetch_consumption(api_key, import_mpan, import_serial, period_from, period_to)
    export_data = octopus.fetch_consumption(api_key, export_mpan, export_serial, period_from, period_to)

    # Fetch tariff info
    print("Fetching tariff rates...")
    tariffs = octopus.get_active_tariffs(api_key, account, date_str)

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
    print("Fetching solar generation data...")
    solar_points = solis.fetch_inverter_day(solis_id, solis_secret, solis_sn, date_str, solis_tz)
    solar_gen = solar_points[-1].get("eToday", 0) if solar_points else 0

    # Calculate costs
    costs = calculate_costs(import_data, export_data, solar_gen, import_rates, export_rate)

    # Print summary
    print(f"\n{'='*50}")
    print(f"  Date:             {date_str}")
    print(f"  Solar generated:  {costs['solar_generation_kwh']:.1f} kWh")
    print(f"  Self-consumed:    {costs['self_consumption_kwh']:.1f} kWh")
    print(f"  Grid import:      {costs['total_import_kwh']:.1f} kWh")
    print(f"  Grid export:      {costs['total_export_kwh']:.1f} kWh")
    print(f"  Import cost:      \u00a3{costs['total_cost_pence']/100:.2f}")
    print(f"  Export earnings:  \u00a3{costs['export_earnings_pence']/100:.2f}")
    print(f"  Solar savings:    \u00a3{costs['solar_savings_pence']/100:.2f}")
    print(f"  Net cost:         \u00a3{costs['net_cost_pence']/100:.2f}")
    print(f"  Total benefit:    \u00a3{(costs['solar_savings_pence']+costs['export_earnings_pence'])/100:.2f}")
    print(f"{'='*50}")

    # Generate dashboard
    half_hourly = build_half_hourly_data(import_data, export_data, import_rates)
    html = generate_html(date_str, costs, half_hourly, solar_points)
    output_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
    with open(output_path, "w") as f:
        f.write(html)
    print(f"\nDashboard written to {output_path}")


if __name__ == "__main__":
    main()
