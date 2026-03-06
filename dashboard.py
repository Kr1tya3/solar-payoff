"""Generate a multi-timeframe solar energy dashboard from stored data."""

import json
import os
import sys

from dotenv import load_dotenv

import db

load_dotenv()


def generate_html(daily_data: list[dict], detail_by_date: dict, solar_by_date: dict) -> str:
    """Generate the full dashboard HTML with embedded data."""

    # Aggregate totals
    totals = {
        "generation_kwh": sum(d["generation_kwh"] or 0 for d in daily_data),
        "import_kwh": sum(d["import_kwh"] or 0 for d in daily_data),
        "export_kwh": sum(d["export_kwh"] or 0 for d in daily_data),
        "self_consumption_kwh": sum(d["self_consumption_kwh"] or 0 for d in daily_data),
        "import_cost_pence": sum(d["import_cost_pence"] or 0 for d in daily_data),
        "standing_charge_pence": sum(d["standing_charge_pence"] or 0 for d in daily_data),
        "export_earnings_pence": sum(d["export_earnings_pence"] or 0 for d in daily_data),
        "solar_savings_pence": sum(d["solar_savings_pence"] or 0 for d in daily_data),
        "day_import_kwh": sum(d["day_import_kwh"] or 0 for d in daily_data),
        "night_import_kwh": sum(d["night_import_kwh"] or 0 for d in daily_data),
        "days": len(daily_data),
    }
    totals["total_cost_pence"] = totals["import_cost_pence"] + totals["standing_charge_pence"]
    totals["net_cost_pence"] = totals["total_cost_pence"] - totals["export_earnings_pence"]
    totals["total_benefit_pence"] = totals["solar_savings_pence"] + totals["export_earnings_pence"]

    # Serialize data for JS
    daily_json = json.dumps(daily_data, default=str)
    detail_json = json.dumps(detail_by_date, default=str)
    solar_json = json.dumps(solar_by_date, default=str)
    totals_json = json.dumps(totals)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Solar Energy Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
:root {{
  --bg: #0f172a; --card: #1e293b; --border: #334155;
  --text: #e2e8f0; --muted: #94a3b8;
  --green: #22c55e; --yellow: #eab308; --blue: #3b82f6;
  --red: #ef4444; --purple: #a855f7; --orange: #f97316;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: var(--bg); color: var(--text); padding: 1.5rem; max-width: 1400px; margin: 0 auto; }}
h1 {{ font-size: 1.5rem; margin-bottom: 0.25rem; }}
.header {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 1rem; margin-bottom: 1.5rem; }}
.subtitle {{ color: var(--muted); font-size: 0.9rem; }}
.tabs {{ display: flex; gap: 0.5rem; flex-wrap: wrap; }}
.tab {{ padding: 0.4rem 1rem; border-radius: 0.5rem; border: 1px solid var(--border);
        background: var(--card); color: var(--muted); cursor: pointer; font-size: 0.85rem; }}
.tab.active {{ background: var(--blue); color: white; border-color: var(--blue); }}
.tab:hover {{ border-color: var(--blue); }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }}
.card {{ background: var(--card); border: 1px solid var(--border); border-radius: 0.75rem; padding: 1.25rem; }}
.card-label {{ font-size: 0.75rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.5rem; }}
.card-value {{ font-size: 1.5rem; font-weight: 700; }}
.card-sub {{ font-size: 0.78rem; color: var(--muted); margin-top: 0.25rem; }}
.green {{ color: var(--green); }} .yellow {{ color: var(--yellow); }}
.blue {{ color: var(--blue); }} .red {{ color: var(--red); }}
.purple {{ color: var(--purple); }} .orange {{ color: var(--orange); }}
.chart-container {{ background: var(--card); border: 1px solid var(--border); border-radius: 0.75rem; padding: 1.25rem; margin-bottom: 1.5rem; }}
.chart-title {{ font-size: 1rem; font-weight: 600; margin-bottom: 1rem; }}
.chart-wrap {{ position: relative; height: 300px; }}
.back-btn {{ display: none; padding: 0.4rem 1rem; border-radius: 0.5rem; border: 1px solid var(--border);
             background: var(--card); color: var(--muted); cursor: pointer; font-size: 0.85rem; margin-bottom: 1rem; }}
.back-btn:hover {{ border-color: var(--blue); color: var(--text); }}
#daily-view {{ display: none; }}
.charts-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; }}
@media (max-width: 900px) {{ .charts-row {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>

<!-- Overview view -->
<div id="overview-view">
  <div class="header">
    <div>
      <h1>Solar Energy Dashboard</h1>
      <p class="subtitle" id="date-range"></p>
    </div>
    <div class="tabs" id="period-tabs">
      <div class="tab" data-period="7">7 Days</div>
      <div class="tab" data-period="30">30 Days</div>
      <div class="tab" data-period="90">90 Days</div>
      <div class="tab active" data-period="all">All Time</div>
    </div>
  </div>

  <div class="grid" id="summary-cards"></div>

  <div class="charts-row">
    <div class="chart-container">
      <div class="chart-title">Daily Energy (kWh)</div>
      <div class="chart-wrap"><canvas id="dailyEnergyChart"></canvas></div>
    </div>
    <div class="chart-container">
      <div class="chart-title">Daily Costs &amp; Earnings (p)</div>
      <div class="chart-wrap"><canvas id="dailyCostChart"></canvas></div>
    </div>
  </div>

  <div class="chart-container">
    <div class="chart-title">Cumulative Solar Benefit</div>
    <div class="chart-wrap"><canvas id="cumulativeChart"></canvas></div>
  </div>

  <div class="charts-row">
    <div class="chart-container">
      <div class="chart-title">Energy Flow Breakdown</div>
      <div class="chart-wrap" style="height:250px"><canvas id="flowChart"></canvas></div>
    </div>
    <div class="chart-container">
      <div class="chart-title">Financial Summary</div>
      <div class="chart-wrap" style="height:250px"><canvas id="financialChart"></canvas></div>
    </div>
  </div>
</div>

<!-- Daily detail view -->
<div id="daily-view">
  <button class="back-btn" id="back-btn" onclick="showOverview()">&larr; Back to overview</button>
  <div class="header">
    <div>
      <h1 id="detail-title">Daily Detail</h1>
      <p class="subtitle" id="detail-rates"></p>
    </div>
  </div>

  <div class="grid" id="detail-cards"></div>

  <div class="chart-container">
    <div class="chart-title">Solar Generation (5-min intervals)</div>
    <div class="chart-wrap"><canvas id="solarChart"></canvas></div>
  </div>

  <div class="chart-container">
    <div class="chart-title">Grid Import / Export (half-hourly)</div>
    <div class="chart-wrap"><canvas id="gridChart"></canvas></div>
  </div>
</div>

<script>
const allDaily = {daily_json};
const detailByDate = {detail_json};
const solarByDate = {solar_json};

Chart.defaults.color = '#94a3b8';
Chart.defaults.borderColor = '#334155';

let currentPeriod = 'all';
let charts = {{}};

function destroyChart(name) {{
  if (charts[name]) {{ charts[name].destroy(); charts[name] = null; }}
}}

function filterData(period) {{
  if (period === 'all') return allDaily;
  const n = parseInt(period);
  return allDaily.slice(-n);
}}

function fmt(pence) {{ return '\\u00a3' + (pence / 100).toFixed(2); }}
function fmtKwh(v) {{ return v.toFixed(1) + ' kWh'; }}

function sumField(data, field) {{
  return data.reduce((s, d) => s + (d[field] || 0), 0);
}}

function renderSummaryCards(data) {{
  const gen = sumField(data, 'generation_kwh');
  const imp = sumField(data, 'import_kwh');
  const exp = sumField(data, 'export_kwh');
  const self = sumField(data, 'self_consumption_kwh');
  const impCost = sumField(data, 'import_cost_pence') + sumField(data, 'standing_charge_pence');
  const expEarn = sumField(data, 'export_earnings_pence');
  const savings = sumField(data, 'solar_savings_pence');
  const benefit = savings + expEarn;
  const net = impCost - expEarn;
  const selfPct = gen > 0 ? (self / gen * 100).toFixed(0) : 0;
  const days = data.length;

  document.getElementById('summary-cards').innerHTML = `
    <div class="card"><div class="card-label">Solar Generated</div>
      <div class="card-value yellow">${{fmtKwh(gen)}}</div>
      <div class="card-sub">${{fmtKwh(gen/days)}}/day avg</div></div>
    <div class="card"><div class="card-label">Self-consumed</div>
      <div class="card-value orange">${{fmtKwh(self)}}</div>
      <div class="card-sub">${{selfPct}}% of generation</div></div>
    <div class="card"><div class="card-label">Grid Import</div>
      <div class="card-value red">${{fmtKwh(imp)}}</div>
      <div class="card-sub">${{fmtKwh(imp/days)}}/day avg</div></div>
    <div class="card"><div class="card-label">Grid Export</div>
      <div class="card-value blue">${{fmtKwh(exp)}}</div>
      <div class="card-sub">${{fmtKwh(exp/days)}}/day avg</div></div>
    <div class="card"><div class="card-label">Import Cost</div>
      <div class="card-value red">${{fmt(impCost)}}</div>
      <div class="card-sub">${{fmt(impCost/days)}}/day avg</div></div>
    <div class="card"><div class="card-label">Export Earnings</div>
      <div class="card-value green">${{fmt(expEarn)}}</div>
      <div class="card-sub">${{fmt(expEarn/days)}}/day avg</div></div>
    <div class="card"><div class="card-label">Solar Savings</div>
      <div class="card-value green">${{fmt(savings)}}</div>
      <div class="card-sub">Avoided import cost</div></div>
    <div class="card"><div class="card-label">Total Solar Benefit</div>
      <div class="card-value green">${{fmt(benefit)}}</div>
      <div class="card-sub">${{fmt(benefit/days)}}/day avg</div></div>
  `;
}}

function renderOverviewCharts(data) {{
  const dates = data.map(d => d.date);
  const shortDates = dates.map(d => {{
    const parts = d.split('-');
    return parts[2] + '/' + parts[1];
  }});

  // Daily energy chart
  destroyChart('dailyEnergy');
  charts.dailyEnergy = new Chart(document.getElementById('dailyEnergyChart'), {{
    type: 'bar',
    data: {{
      labels: shortDates,
      datasets: [
        {{ label: 'Generation', data: data.map(d => d.generation_kwh), backgroundColor: 'rgba(234,179,8,0.8)', order: 2 }},
        {{ label: 'Import', data: data.map(d => d.import_kwh), backgroundColor: 'rgba(239,68,68,0.8)', order: 2 }},
        {{ label: 'Export', data: data.map(d => -d.export_kwh), backgroundColor: 'rgba(34,197,94,0.8)', order: 2 }},
      ]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      onClick: (e, elements) => {{
        if (elements.length > 0) {{
          const idx = elements[0].index;
          showDailyDetail(data[idx].date);
        }}
      }},
      scales: {{
        x: {{ ticks: {{ maxRotation: 0, maxTicksLimit: 15 }} }},
        y: {{ title: {{ display: true, text: 'kWh' }} }}
      }},
      plugins: {{
        tooltip: {{
          callbacks: {{
            title: (items) => dates[items[0].dataIndex],
            label: (ctx) => ctx.dataset.label + ': ' + Math.abs(ctx.raw).toFixed(1) + ' kWh'
          }}
        }}
      }}
    }}
  }});

  // Daily cost chart
  destroyChart('dailyCost');
  charts.dailyCost = new Chart(document.getElementById('dailyCostChart'), {{
    type: 'bar',
    data: {{
      labels: shortDates,
      datasets: [
        {{ label: 'Import Cost', data: data.map(d => (d.import_cost_pence||0) + (d.standing_charge_pence||0)),
           backgroundColor: 'rgba(239,68,68,0.8)' }},
        {{ label: 'Export Earnings', data: data.map(d => -(d.export_earnings_pence||0)),
           backgroundColor: 'rgba(34,197,94,0.8)' }},
        {{ label: 'Solar Savings', data: data.map(d => -(d.solar_savings_pence||0)),
           backgroundColor: 'rgba(234,179,8,0.8)' }},
      ]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      onClick: (e, elements) => {{
        if (elements.length > 0) showDailyDetail(data[elements[0].index].date);
      }},
      scales: {{
        x: {{ stacked: true, ticks: {{ maxRotation: 0, maxTicksLimit: 15 }} }},
        y: {{ stacked: true, title: {{ display: true, text: 'Pence' }} }}
      }},
      plugins: {{
        tooltip: {{
          callbacks: {{
            title: (items) => dates[items[0].dataIndex],
            label: (ctx) => ctx.dataset.label + ': ' + Math.abs(ctx.raw).toFixed(1) + 'p'
          }}
        }}
      }}
    }}
  }});

  // Cumulative benefit chart
  destroyChart('cumulative');
  let cumBenefit = 0, cumExport = 0, cumSavings = 0;
  const cumData = data.map(d => {{
    cumExport += (d.export_earnings_pence || 0);
    cumSavings += (d.solar_savings_pence || 0);
    cumBenefit = cumExport + cumSavings;
    return {{ benefit: cumBenefit / 100, exportEarn: cumExport / 100, savings: cumSavings / 100 }};
  }});
  charts.cumulative = new Chart(document.getElementById('cumulativeChart'), {{
    type: 'line',
    data: {{
      labels: shortDates,
      datasets: [
        {{ label: 'Total Benefit', data: cumData.map(d => d.benefit),
           borderColor: '#22c55e', backgroundColor: 'rgba(34,197,94,0.1)', fill: true, pointRadius: 0, borderWidth: 2 }},
        {{ label: 'Export Earnings', data: cumData.map(d => d.exportEarn),
           borderColor: '#3b82f6', borderDash: [5,5], pointRadius: 0, borderWidth: 1.5 }},
        {{ label: 'Solar Savings', data: cumData.map(d => d.savings),
           borderColor: '#eab308', borderDash: [5,5], pointRadius: 0, borderWidth: 1.5 }},
      ]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      scales: {{
        x: {{ ticks: {{ maxRotation: 0, maxTicksLimit: 15 }} }},
        y: {{ title: {{ display: true, text: '\\u00a3' }} }}
      }}
    }}
  }});

  // Energy flow doughnut
  destroyChart('flow');
  const self = sumField(data, 'self_consumption_kwh');
  const exp = sumField(data, 'export_kwh');
  const dayImp = sumField(data, 'day_import_kwh');
  const nightImp = sumField(data, 'night_import_kwh');
  charts.flow = new Chart(document.getElementById('flowChart'), {{
    type: 'doughnut',
    data: {{
      labels: ['Self-consumed', 'Exported', 'Import (Day)', 'Import (Night)'],
      datasets: [{{ data: [self, exp, dayImp, nightImp].map(v => +v.toFixed(1)),
                     backgroundColor: ['#eab308', '#22c55e', '#ef4444', '#3b82f6'] }}]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      plugins: {{ legend: {{ position: 'right' }},
        tooltip: {{ callbacks: {{ label: (ctx) => ctx.label + ': ' + ctx.raw + ' kWh' }} }}
      }}
    }}
  }});

  // Financial doughnut
  destroyChart('financial');
  const impCost = sumField(data, 'import_cost_pence') + sumField(data, 'standing_charge_pence');
  const expEarn = sumField(data, 'export_earnings_pence');
  const savings = sumField(data, 'solar_savings_pence');
  charts.financial = new Chart(document.getElementById('financialChart'), {{
    type: 'doughnut',
    data: {{
      labels: ['Import Cost', 'Export Earnings', 'Solar Savings'],
      datasets: [{{ data: [impCost/100, expEarn/100, savings/100].map(v => +v.toFixed(2)),
                     backgroundColor: ['#ef4444', '#22c55e', '#eab308'] }}]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      plugins: {{ legend: {{ position: 'right' }},
        tooltip: {{ callbacks: {{ label: (ctx) => ctx.label + ': \\u00a3' + ctx.raw.toFixed(2) }} }}
      }}
    }}
  }});

  // Date range subtitle
  if (data.length > 0) {{
    document.getElementById('date-range').textContent =
      data[0].date + ' to ' + data[data.length-1].date + ' (' + data.length + ' days)';
  }}
}}

function showOverview() {{
  document.getElementById('overview-view').style.display = '';
  document.getElementById('daily-view').style.display = 'none';
  document.getElementById('back-btn').style.display = 'none';
}}

function showDailyDetail(date) {{
  const dayData = allDaily.find(d => d.date === date);
  if (!dayData) return;

  document.getElementById('overview-view').style.display = 'none';
  document.getElementById('daily-view').style.display = '';
  document.getElementById('back-btn').style.display = '';
  document.getElementById('detail-title').textContent = 'Daily Detail - ' + date;

  const dayRate = dayData.import_day_rate || 0;
  const nightRate = dayData.import_night_rate || 0;
  const expRate = dayData.export_rate || 0;
  document.getElementById('detail-rates').textContent =
    `Day: ${{dayRate.toFixed(2)}}p/kWh | Night: ${{nightRate.toFixed(2)}}p/kWh | Export: ${{expRate.toFixed(2)}}p/kWh`;

  const gen = dayData.generation_kwh || 0;
  const self = dayData.self_consumption_kwh || 0;
  const selfPct = gen > 0 ? (self/gen*100).toFixed(0) : 0;
  const impCost = (dayData.import_cost_pence||0) + (dayData.standing_charge_pence||0);
  const benefit = (dayData.solar_savings_pence||0) + (dayData.export_earnings_pence||0);

  document.getElementById('detail-cards').innerHTML = `
    <div class="card"><div class="card-label">Solar Generated</div>
      <div class="card-value yellow">${{fmtKwh(gen)}}</div>
      <div class="card-sub">Self-consumed: ${{fmtKwh(self)}} (${{selfPct}}%)</div></div>
    <div class="card"><div class="card-label">Grid Import</div>
      <div class="card-value red">${{fmtKwh(dayData.import_kwh)}}</div>
      <div class="card-sub">Day: ${{fmtKwh(dayData.day_import_kwh)}} / Night: ${{fmtKwh(dayData.night_import_kwh)}}</div></div>
    <div class="card"><div class="card-label">Grid Export</div>
      <div class="card-value blue">${{fmtKwh(dayData.export_kwh)}}</div></div>
    <div class="card"><div class="card-label">Import Cost</div>
      <div class="card-value red">${{fmt(impCost)}}</div>
      <div class="card-sub">Energy ${{fmt(dayData.import_cost_pence)}} + Standing ${{fmt(dayData.standing_charge_pence)}}</div></div>
    <div class="card"><div class="card-label">Export Earnings</div>
      <div class="card-value green">${{fmt(dayData.export_earnings_pence)}}</div></div>
    <div class="card"><div class="card-label">Solar Savings</div>
      <div class="card-value green">${{fmt(dayData.solar_savings_pence)}}</div></div>
    <div class="card"><div class="card-label">Total Benefit</div>
      <div class="card-value green">${{fmt(benefit)}}</div></div>
    <div class="card"><div class="card-label">Net Cost</div>
      <div class="card-value purple">${{fmt(impCost - (dayData.export_earnings_pence||0))}}</div></div>
  `;

  // Solar generation chart
  const solar = solarByDate[date] || [];
  destroyChart('solar');
  const sTimes = solar.map(p => {{
    const parts = p.time_str.split(':');
    return parts.length >= 2 ? parts[0]+':'+parts[1] : p.time_str;
  }});
  charts.solar = new Chart(document.getElementById('solarChart'), {{
    type: 'line',
    data: {{
      labels: sTimes,
      datasets: [{{
        label: 'Solar Power (W)', data: solar.map(p => p.pac_watts),
        borderColor: '#eab308', backgroundColor: 'rgba(234,179,8,0.1)',
        fill: true, pointRadius: 0, borderWidth: 2, tension: 0.3,
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
  const hh = detailByDate[date] || [];
  destroyChart('grid');
  const nightBg = hh.map(r => r.is_night ? 'rgba(59,130,246,0.8)' : 'rgba(239,68,68,0.8)');
  charts.grid = new Chart(document.getElementById('gridChart'), {{
    type: 'bar',
    data: {{
      labels: hh.map(r => {{
        const d = new Date(r.interval_start);
        return String(d.getUTCHours()).padStart(2,'0') + ':' + String(d.getUTCMinutes()).padStart(2,'0');
      }}),
      datasets: [
        {{ label: 'Import (kWh)', data: hh.map(r => r.import_kwh), backgroundColor: nightBg }},
        {{ label: 'Export (kWh)', data: hh.map(r => -r.export_kwh), backgroundColor: 'rgba(34,197,94,0.8)' }},
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
          callbacks: {{ label: (ctx) => ctx.dataset.label + ': ' + Math.abs(ctx.raw).toFixed(3) + ' kWh' }}
        }}
      }}
    }}
  }});
}}

// Tab switching
document.querySelectorAll('.tab').forEach(tab => {{
  tab.addEventListener('click', () => {{
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    currentPeriod = tab.dataset.period;
    const data = filterData(currentPeriod);
    renderSummaryCards(data);
    renderOverviewCharts(data);
  }});
}});

// Initial render
renderSummaryCards(allDaily);
renderOverviewCharts(allDaily);
</script>
</body>
</html>"""


def main():
    db.init_db()
    conn = db.get_connection()

    daily_data = db.get_daily_summaries(conn)
    if not daily_data:
        print("No data in database. Run 'uv run collect.py --backfill' first.")
        sys.exit(1)

    print(f"Generating dashboard for {len(daily_data)} days...")

    # Load detail data for each date
    detail_by_date = {}
    solar_by_date = {}
    for d in daily_data:
        date = d["date"]
        detail_by_date[date] = db.get_half_hourly(conn, date)
        solar_by_date[date] = db.get_solar_5min(conn, date)

    conn.close()

    html = generate_html(daily_data, detail_by_date, solar_by_date)
    output_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
    with open(output_path, "w") as f:
        f.write(html)

    first = daily_data[0]["date"]
    last = daily_data[-1]["date"]
    total_benefit = sum(
        (d["solar_savings_pence"] or 0) + (d["export_earnings_pence"] or 0) for d in daily_data
    )
    print(f"Period: {first} to {last} ({len(daily_data)} days)")
    print(f"Total solar benefit: \u00a3{total_benefit/100:.2f}")
    print(f"Dashboard written to {output_path}")


if __name__ == "__main__":
    main()
