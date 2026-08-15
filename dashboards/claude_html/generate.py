"""Regenerates dashboards/claude_html/output/cfo_dashboard.html from
dashboards/claude_html/config/dashboard.md.

Every metric's definition, format, chart type, and SQL live in dashboard.md -- this
script does not encode any business logic of its own. It: (1) parses that file,
(2) runs each `live`/`placeholder-empty` query against storage/warehouse.duckdb,
(3) reads main_silver.user_entity_access + dim_entity to build the same role/entity
scopes Superset's RLS already enforces (see ops/superset/setup_superset.py), and
(4) renders one self-contained HTML file with a client-side role switcher.

Reminder (see dashboard.md's "Roles & access scope" section): the switcher is a
display filter, not access control -- every viewer's browser receives every
entity's data regardless of which view is selected. Where this file is hosted is
the actual control point.

Run after `dbt build` has refreshed Gold:
    python dashboards/claude_html/generate.py
"""
import json
import re
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import duckdb

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config" / "dashboard.md"
OUTPUT_PATH = SCRIPT_DIR / "output" / "cfo_dashboard.html"
WAREHOUSE_PATH = SCRIPT_DIR.parent.parent / "storage" / "warehouse.duckdb"

METRIC_FIELD_RE = re.compile(
    r"^-\s*(Status|Format|Chart|Definition|Note|XField|SeriesField|LabelField)\s*:\s*(.*)$",
    re.IGNORECASE,
)
SQL_BLOCK_RE = re.compile(r"```sql\s*\n(.*?)```", re.DOTALL)


def parse_config(text: str) -> list[dict]:
    """Splits dashboard.md into sections/metrics. Text before the first '## '
    heading is documentation for humans, not dashboard config, and is ignored."""
    first = text.find("\n## ")
    if first == -1:
        raise ValueError("dashboard.md has no '## ' section headings")
    body = text[first + 1 :]

    sections = []
    for section_chunk in re.split(r"\n(?=## (?!#))", body):
        section_chunk = section_chunk.strip("\n")
        if not section_chunk.startswith("## "):
            continue
        lines = section_chunk.split("\n")
        section_title = lines[0][3:].strip()
        rest = "\n".join(lines[1:])

        metrics = []
        intro_parts = []
        for metric_chunk in re.split(r"\n(?=### )", rest):
            metric_chunk = metric_chunk.strip("\n")
            if not metric_chunk.startswith("### "):
                if metric_chunk.strip():
                    intro_parts.append(metric_chunk.strip())
                continue
            mlines = metric_chunk.split("\n")
            metric_title = mlines[0][4:].strip()
            mbody = "\n".join(mlines[1:])

            fields = {
                "status": None, "format": None, "chart": None,
                "definition": "", "note": "",
                "xfield": None, "seriesfield": None, "labelfield": None,
            }
            current_key = None
            for line in mbody.split("\n"):
                stripped = line.strip()
                m = METRIC_FIELD_RE.match(stripped)
                if m:
                    current_key = m.group(1).lower()
                    fields[current_key] = m.group(2).strip()
                elif current_key and stripped and not stripped.startswith(("-", "```")):
                    # a wrapped continuation line of the current field's prose
                    fields[current_key] = (fields[current_key] + " " + stripped).strip()
                elif not stripped or stripped.startswith("```"):
                    current_key = None

            sql_match = SQL_BLOCK_RE.search(mbody)
            sql = sql_match.group(1).strip() if sql_match else None

            if fields["status"] not in ("live", "placeholder-empty", "placeholder-no-source"):
                raise ValueError(
                    f"metric '{metric_title}' has invalid/missing Status: {fields['status']!r}"
                )

            metrics.append({
                "title": metric_title,
                "status": fields["status"],
                "format": fields["format"],
                "chart": fields["chart"],
                "definition": fields["definition"],
                "note": fields["note"],
                "x_field": fields["xfield"],
                "series_field": fields["seriesfield"],
                "label_field": fields["labelfield"],
                "sql": sql,
            })

        if not metrics:
            continue  # a '## ' heading with no '### ' children is documentation, not a section
        sections.append({
            "title": section_title,
            "intro": " ".join(intro_parts),
            "metrics": metrics,
        })
    return sections


def to_jsonable(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if value is None or isinstance(value, (int, float, str, bool)):
        return value
    return str(value)


def run_metrics(con: duckdb.DuckDBPyConnection, sections: list[dict]) -> str | None:
    data_as_of_candidates = []
    for section in sections:
        for metric in section["metrics"]:
            metric["columns"], metric["rows"], metric["row_count"], metric["error"] = [], [], 0, None
            if metric["status"] not in ("live", "placeholder-empty") or not metric["sql"]:
                continue
            try:
                result = con.execute(metric["sql"])
                cols = [d[0] for d in result.description]
                raw_rows = result.fetchall()
            except Exception as exc:  # noqa: BLE001 -- surfaced on the card, not swallowed
                metric["error"] = str(exc)
                print(f"  ERROR running '{metric['title']}': {exc}", file=sys.stderr)
                continue

            rows = [{cols[i]: to_jsonable(v) for i, v in enumerate(r)} for r in raw_rows]
            metric["columns"], metric["rows"], metric["row_count"] = cols, rows, len(rows)
            for row in rows:
                for key in ("period_end", "posted_at", "due_date"):
                    if row.get(key):
                        data_as_of_candidates.append(row[key])

    return max(data_as_of_candidates) if data_as_of_candidates else None


def build_views(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """One view per distinct governed (role, entity_id) in user_entity_access -- the
    same table Superset's RLS reads (ops/superset/setup_superset.py). Not a separate
    access model; this just reads the existing one."""
    entity_rows = con.execute(
        "select entity_id, entity_name, parent_entity_id from main_silver.dim_entity"
    ).fetchall()
    entity_name = {r[0]: r[1] for r in entity_rows}
    children: dict[str, list[str]] = {}
    for entity_id, _name, parent_id in entity_rows:
        if parent_id:
            children.setdefault(parent_id, []).append(entity_id)

    def descendants(root: str) -> set[str]:
        seen, stack = set(), [root]
        while stack:
            current = stack.pop()
            for child in children.get(current, []):
                if child not in seen:
                    seen.add(child)
                    stack.append(child)
        return seen

    access_rows = con.execute(
        """
        select distinct role, entity_id
        from main_silver.user_entity_access
        where effective_from <= current_date
          and (effective_to is null or effective_to > current_date)
        order by role, entity_id
        """
    ).fetchall()

    views, seen_ids = [], set()
    for role, entity_id in access_rows:
        if role == "GROUP_FINANCE_OWNER":
            view = {
                "id": "holdings",
                "label": "Holdings — Group Finance Owner (all companies)",
                "allow_all": True,
                "allowed": [],
            }
        else:
            allowed = sorted({entity_id} | descendants(entity_id))
            name = entity_name.get(entity_id, entity_id)
            view = {
                "id": f"controller-{entity_id.lower()}",
                "label": f"Regional Controller — {name}",
                "allow_all": False,
                "allowed": allowed,
            }
        if view["id"] not in seen_ids:
            seen_ids.add(view["id"])
            views.append(view)

    if not views:
        raise ValueError("main_silver.user_entity_access has no currently-effective rows")
    return views


HTML_SHELL = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root {
  color-scheme: light;
  --surface-1:      #fcfcfb;
  --page-plane:      #f9f9f7;
  --text-primary:   #0b0b0b;
  --text-secondary: #52514e;
  --text-muted:     #898781;
  --gridline:       #e1e0d9;
  --baseline:       #c3c2b7;
  --border:         rgba(11,11,11,0.10);
  --series-1: #2a78d6; --series-2: #eb6834; --series-3: #1baf7a; --series-4: #eda100;
  --series-5: #e87ba4; --series-6: #008300; --series-7: #4a3aa7; --series-8: #e34948;
  --status-good: #0ca30c; --status-warning: #fab219; --status-serious: #ec835a; --status-critical: #d03b3b;
}
@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --surface-1:      #1a1a19;
    --page-plane:      #0d0d0d;
    --text-primary:   #ffffff;
    --text-secondary: #c3c2b7;
    --text-muted:     #898781;
    --gridline:       #2c2c2a;
    --baseline:       #383835;
    --border:         rgba(255,255,255,0.10);
    --series-1: #3987e5; --series-2: #d95926; --series-3: #199e70; --series-4: #c98500;
    --series-5: #d55181; --series-6: #008300; --series-7: #9085e9; --series-8: #e66767;
    --status-good: #0ca30c; --status-warning: #fab219; --status-serious: #ec835a; --status-critical: #d03b3b;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--page-plane); color: var(--text-primary);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  font-size: 15px; line-height: 1.45;
}
header {
  padding: 20px 28px; background: var(--surface-1); border-bottom: 1px solid var(--border);
  display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px;
  position: sticky; top: 0; z-index: 10;
}
header h1 { font-size: 19px; margin: 0 0 2px; }
.freshness { color: var(--text-muted); font-size: 12.5px; }
.view-picker { display: flex; align-items: center; gap: 8px; }
.view-picker label { font-size: 12.5px; color: var(--text-secondary); }
.view-picker select {
  font: inherit; padding: 7px 10px; border-radius: 8px; border: 1px solid var(--border);
  background: var(--surface-1); color: var(--text-primary);
}
main { padding: 24px 28px 60px; max-width: 1400px; margin: 0 auto; }
.dash-section { margin-bottom: 34px; }
.dash-section h2 { font-size: 16px; margin: 0 0 4px; }
.section-intro { color: var(--text-secondary); font-size: 13px; margin: 0 0 14px; max-width: 70ch; }
.metric-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 14px;
}
.metric-card {
  background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px;
  padding: 16px; display: flex; flex-direction: column; min-width: 0;
}
.metric-card h3 { font-size: 14px; margin: 0 0 4px; }
.metric-def { color: var(--text-secondary); font-size: 12.5px; margin: 0 0 12px; }
.metric-note { color: var(--text-muted); font-size: 11.5px; font-style: italic; margin: 10px 0 0; }
.metric-body { flex: 1; min-height: 40px; }
.chart-svg { width: 100%; height: auto; overflow: visible; }
.axis-label { fill: var(--text-muted); font-size: 9.5px; }
.baseline { stroke: var(--baseline); stroke-width: 1; }
.legend { display: flex; flex-wrap: wrap; gap: 10px 14px; margin-top: 8px; }
.legend-item { display: inline-flex; align-items: center; gap: 5px; font-size: 11.5px; color: var(--text-secondary); }
.swatch { width: 9px; height: 9px; border-radius: 2px; display: inline-block; }
.stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 10px; }
.stat-tile { padding: 10px 0; }
.stat-label { font-size: 11px; color: var(--text-secondary); margin-bottom: 3px; }
.stat-value { font-size: 22px; font-weight: 600; }
.stat-note { font-size: 10.5px; color: var(--text-muted); margin-top: 2px; }
.table-wrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 12.5px; }
th, td {
  text-align: left; padding: 6px 10px 6px 0; border-bottom: 1px solid var(--gridline);
  font-variant-numeric: tabular-nums; white-space: nowrap;
}
th { color: var(--text-muted); font-weight: 500; font-size: 11px; text-transform: uppercase; letter-spacing: 0.02em; }
.placeholder {
  display: flex; gap: 10px; align-items: flex-start; color: var(--text-muted);
  font-size: 12.5px; background: var(--page-plane); border-radius: 8px; padding: 12px; border: 1px dashed var(--border);
}
.placeholder-icon { font-size: 16px; line-height: 1; }
.error-card {
  color: var(--status-critical); font-size: 12.5px; background: var(--page-plane);
  border-radius: 8px; padding: 12px; border: 1px solid var(--border);
}
.badge {
  display: inline-block; font-size: 10px; font-weight: 600; padding: 1px 6px; border-radius: 4px;
  margin-left: 6px; vertical-align: middle;
}
.badge-critical { background: var(--status-critical); color: #fff; }
footer { padding: 20px 28px 40px; color: var(--text-muted); font-size: 11.5px; max-width: 1400px; margin: 0 auto; }
</style>
</head>
<body>
<header>
  <div>
    <h1>__TITLE__</h1>
    <div class="freshness" id="freshness-note"></div>
  </div>
  <div class="view-picker">
    <label for="view-select">Viewing as</label>
    <select id="view-select"></select>
  </div>
</header>
<main id="dashboard-main"></main>
<footer>
  Generated by <code>dashboards/claude_html/generate.py</code> from
  <code>dashboards/claude_html/config/dashboard.md</code>. The role switcher above changes what's
  displayed, not what this file contains &mdash; every entity's data is embedded in this page
  regardless of the selected view. Re-run the generator after <code>dbt build</code> to refresh.
</footer>
<script id="dashboard-data" type="application/json">__DASHBOARD_JSON__</script>
<script>
const DASHBOARD = JSON.parse(document.getElementById('dashboard-data').textContent);
let currentViewId = DASHBOARD.default_view;

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function truncateLabel(s, n = 12) {
  s = String(s ?? '');
  return s.length > n ? s.slice(0, n - 1) + '…' : s;
}
function prettyCol(c) {
  return String(c).replace(/_/g, ' ').replace(/\b\w/g, m => m.toUpperCase());
}
function fmtValue(format, value, currency) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  const num = Number(value);
  switch (format) {
    case 'currency':
      try {
        return new Intl.NumberFormat('en-US', { style: 'currency', currency: currency || 'MYR', maximumFractionDigits: 0 }).format(num);
      } catch (e) {
        return (currency || '') + ' ' + num.toLocaleString(undefined, { maximumFractionDigits: 0 });
      }
    case 'percent': return num.toFixed(1) + '%';
    case 'days': return num.toFixed(1) + ' days';
    case 'ratio': return num.toFixed(4);
    case 'count': return num.toLocaleString();
    default: return String(value);
  }
}
function formatCell(col, value) {
  if (value === null || value === undefined) return '';
  if (col.endsWith('_pct')) return Number(value).toFixed(1) + '%';
  if (col === 'is_major_variance' || col === 'is_breached') return value ? 'Yes' : 'No';
  if (typeof value === 'number') return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  return String(value);
}
function isRowVisible(row, view) {
  return view.allow_all || (row.entity_id != null && view.allowed.includes(row.entity_id));
}

let ENTITY_COLOR_MAP = null;
function buildEntityColorMap() {
  const order = [], seen = new Set();
  for (const section of DASHBOARD.sections) {
    for (const metric of section.metrics) {
      for (const row of (metric.rows || [])) {
        const id = row.entity_id;
        if (id && !seen.has(id)) { seen.add(id); order.push(id); }
      }
    }
  }
  const slots = [1,2,3,4,5,6,7,8].map(n => `var(--series-${n})`);
  const map = {};
  order.forEach((id, i) => { map[id] = slots[i % slots.length]; });
  return map;
}
function getEntityColor(entityId) {
  if (!ENTITY_COLOR_MAP) ENTITY_COLOR_MAP = buildEntityColorMap();
  return ENTITY_COLOR_MAP[entityId] || 'var(--text-muted)';
}

function round1(n) { return Math.round(n * 10) / 10; }

function barPath(x, top, w, h, r, roundTop) {
  r = Math.max(0, Math.min(r, w / 2, h));
  x = round1(x); top = round1(top); w = round1(w); h = round1(h);
  const bottom = round1(top + h);
  if (r < 0.5) return `M${x},${top} h${w} v${h} h${-w} Z`;
  if (roundTop) {
    return `M${x},${bottom} L${x},${round1(top + r)} Q${x},${top} ${round1(x + r)},${top} ` +
           `L${round1(x + w - r)},${top} Q${x + w},${top} ${x + w},${round1(top + r)} L${x + w},${bottom} Z`;
  }
  return `M${x},${top} L${x + w},${top} L${x + w},${round1(bottom - r)} Q${x + w},${bottom} ${round1(x + w - r)},${bottom} ` +
         `L${round1(x + r)},${bottom} Q${x},${bottom} ${x},${round1(bottom - r)} Z`;
}

const MAX_CHART_SERIES = 7; // + one "Other" fold = 8, matching the 8-slot categorical palette

// When a (category, series) cell has more than one row -- e.g. 12 months of history behind
// one entity/account bar -- the *latest* period is what a snapshot chart should show, not a
// sum (summing 12 months of a percentage or a point-in-time balance is meaningless). Callers
// pass rows pre-sorted chronologically (every query below orders by period), so "last row for
// this cell" is "latest period for this cell".
function latestByCell(rows, xField, seriesField) {
  const cell = new Map();
  for (const r of rows) {
    const key = String(r[xField] ?? '') + ' ' + (seriesField ? String(r[seriesField] ?? '') : '');
    cell.set(key, r); // later rows overwrite earlier ones
  }
  return cell;
}

function prepareChartData(rows, xField, seriesField) {
  xField = xField || 'entity_name';
  const categories = [], catSeen = new Set();
  for (const r of rows) {
    const cat = String(r[xField] ?? '');
    if (!catSeen.has(cat)) { catSeen.add(cat); categories.push(cat); }
  }
  const cell = latestByCell(rows, xField, seriesField);

  if (seriesField) {
    const totals = new Map();
    for (const r of rows) {
      const s = String(r[seriesField] ?? '');
      totals.set(s, (totals.get(s) || 0) + Math.abs(Number(r.value) || 0));
    }
    let names = [...totals.keys()];
    let otherNames = [];
    if (names.length > MAX_CHART_SERIES) {
      names.sort((a, b) => totals.get(b) - totals.get(a));
      otherNames = names.slice(MAX_CHART_SERIES);
      names = names.slice(0, MAX_CHART_SERIES);
    }
    const series = names.map(name => {
      const sample = rows.find(r => String(r[seriesField]) === name) || {};
      return {
        name, color: getEntityColor(sample.entity_id),
        values: categories.map(c => {
          const r = cell.get(c + ' ' + name);
          return r ? Number(r.value) || 0 : null;
        }),
      };
    });
    if (otherNames.length) {
      const otherSet = new Set(otherNames);
      const byCat = {};
      for (const cat of categories) {
        let sum = 0, any = false;
        for (const name of otherNames) {
          const r = cell.get(cat + ' ' + name);
          if (r) { sum += Number(r.value) || 0; any = true; }
        }
        byCat[cat] = any ? sum : null;
      }
      series.push({ name: `Other (${otherNames.length})`, color: 'var(--text-muted)', values: categories.map(c => byCat[c]) });
    }
    return { categories, series, showLegend: series.length > 1 };
  }

  const values = [], colors = [];
  for (const cat of categories) {
    const r = cell.get(cat + ' ');
    values.push(r ? Number(r.value) || 0 : null);
    colors.push(getEntityColor(r ? r.entity_id : null));
  }
  return { categories, series: [{ name: null, values, colors }], showLegend: false };
}

function renderEmpty(container, message) {
  container.innerHTML = `<div class="placeholder"><span class="placeholder-icon">◌</span><div>${escapeHtml(message)}</div></div>`;
}
function renderError(container, message) {
  container.innerHTML = `<div class="error-card"><strong>Query error</strong> — ${escapeHtml(message)}</div>`;
}
function renderPlaceholder(container, note, rowCount, status) {
  const extra = status === 'placeholder-empty' ? ` (query returns ${rowCount} row${rowCount === 1 ? '' : 's'} today)` : '';
  container.innerHTML = `<div class="placeholder"><span class="placeholder-icon">◌</span><div>${escapeHtml(note || 'Not available yet.')}${escapeHtml(extra)}</div></div>`;
}
function renderStatTiles(container, rows, format, labelFields) {
  if (!rows.length) { renderEmpty(container, 'No rows for this view.'); return; }
  const tiles = rows.map(r => {
    const label = labelFields.map(f => r[f]).filter(v => v !== null && v !== undefined).join(' · ');
    return `<div class="stat-tile"><div class="stat-label">${escapeHtml(label)}</div>` +
           `<div class="stat-value">${escapeHtml(fmtValue(format, r.value, r.currency))}</div>` +
           (r.source ? `<div class="stat-note">${escapeHtml(r.source)}</div>` : '') + `</div>`;
  }).join('');
  container.innerHTML = `<div class="stat-grid">${tiles}</div>`;
}
function renderTable(container, columns, rows) {
  if (!rows.length) { renderEmpty(container, 'No rows for this view.'); return; }
  const cols = columns.filter(c => c !== 'entity_id');
  const thead = cols.map(c => `<th>${escapeHtml(prettyCol(c))}</th>`).join('');
  const tbody = rows.map(r => `<tr>${cols.map(c => {
    const badge = (c === 'is_major_variance' || c === 'is_breached') && r[c] ? '<span class="badge badge-critical">FLAG</span>' : '';
    return `<td>${escapeHtml(formatCell(c, r[c]))}${badge}</td>`;
  }).join('')}</tr>`).join('');
  container.innerHTML = `<div class="table-wrap"><table><thead><tr>${thead}</tr></thead><tbody>${tbody}</tbody></table></div>`;
}
function renderBarChart(container, data, format) {
  const { categories, series, showLegend } = data;
  if (!categories.length) { renderEmpty(container, 'No rows for this view.'); return; }
  const width = 640, topPad = 16, chartHeight = 180, axisPad = 26;
  const svgHeight = topPad + chartHeight + axisPad;
  const allVals = series.flatMap(s => s.values.filter(v => v !== null && v !== undefined));
  const maxVal = Math.max(0, ...allVals, 0.0001);
  const minVal = Math.min(0, ...allVals);
  const range = (maxVal - minVal) || 1;
  const plotLeft = 8, plotRight = width - 8;
  const bandW = (plotRight - plotLeft) / categories.length;
  const barThick = Math.max(4, Math.min(24, (bandW - 10) / Math.max(1, series.length)));
  function yFor(v) { return topPad + chartHeight - ((v - minVal) / range) * chartHeight; }
  const zeroY = yFor(0);

  let bars = '';
  categories.forEach((cat, ci) => {
    const groupW = series.length * barThick + (series.length - 1) * 2;
    const groupX = plotLeft + ci * bandW + (bandW - groupW) / 2;
    series.forEach((s, si) => {
      const v = s.values[ci];
      if (v === null || v === undefined) return;
      const x = groupX + si * (barThick + 2);
      const y0 = zeroY, y1 = yFor(v);
      const top = Math.min(y0, y1), h = Math.max(1, Math.abs(y1 - y0));
      const roundTop = v >= 0;
      const color = s.color || (s.colors ? s.colors[ci] : 'var(--series-1)');
      const label = (s.name ? `${cat} · ${s.name}` : cat) + ': ' + fmtValue(format, v, null);
      bars += `<path d="${barPath(x, top, barThick, h, 4, roundTop)}" fill="${color}"><title>${escapeHtml(label)}</title></path>`;
    });
  });
  let xLabels = '';
  categories.forEach((cat, ci) => {
    const cx = plotLeft + ci * bandW + bandW / 2;
    xLabels += `<text x="${round1(cx)}" y="${topPad + chartHeight + 16}" class="axis-label" text-anchor="middle">${escapeHtml(truncateLabel(cat))}</text>`;
  });
  const legend = showLegend
    ? `<div class="legend">${series.map(s => `<span class="legend-item"><span class="swatch" style="background:${s.color}"></span>${escapeHtml(s.name)}</span>`).join('')}</div>`
    : '';
  container.innerHTML =
    `<svg viewBox="0 0 ${width} ${svgHeight}" class="chart-svg" role="img" aria-label="chart">` +
    `<line x1="${plotLeft}" y1="${round1(zeroY)}" x2="${plotRight}" y2="${round1(zeroY)}" class="baseline" />` +
    bars + xLabels + `</svg>${legend}`;
}

function render() {
  const view = DASHBOARD.views.find(v => v.id === currentViewId) || DASHBOARD.views[0];
  const main = document.getElementById('dashboard-main');
  main.innerHTML = '';
  for (const section of DASHBOARD.sections) {
    const sectionEl = document.createElement('section');
    sectionEl.className = 'dash-section';
    sectionEl.innerHTML = `<h2>${escapeHtml(section.title)}</h2>` +
      (section.intro ? `<p class="section-intro">${escapeHtml(section.intro)}</p>` : '');
    const grid = document.createElement('div');
    grid.className = 'metric-grid';
    for (const metric of section.metrics) {
      const card = document.createElement('article');
      card.className = 'metric-card';
      const isPlaceholder = metric.status === 'placeholder-no-source' || metric.status === 'placeholder-empty';
      card.innerHTML = `<h3>${escapeHtml(metric.title)}</h3>` +
        `<p class="metric-def">${escapeHtml(metric.definition || '')}</p>` +
        `<div class="metric-body"></div>` +
        (metric.note && !isPlaceholder ? `<p class="metric-note">${escapeHtml(metric.note)}</p>` : '');
      const body = card.querySelector('.metric-body');
      if (metric.error) {
        renderError(body, metric.error);
      } else if (isPlaceholder) {
        renderPlaceholder(body, metric.note, metric.row_count, metric.status);
      } else {
        const rows = (metric.rows || []).filter(r => isRowVisible(r, view));
        if (metric.chart === 'table') {
          renderTable(body, metric.columns, rows);
        } else if (metric.chart === 'stat') {
          const labelFields = (metric.label_field || 'entity_name').split(',').map(s => s.trim());
          renderStatTiles(body, rows, metric.format, labelFields);
        } else {
          renderBarChart(body, prepareChartData(rows, metric.x_field, metric.series_field), metric.format);
        }
      }
      grid.appendChild(card);
    }
    sectionEl.appendChild(grid);
    main.appendChild(sectionEl);
  }
}

function init() {
  const select = document.getElementById('view-select');
  select.innerHTML = DASHBOARD.views.map(v => `<option value="${v.id}">${escapeHtml(v.label)}</option>`).join('');
  select.value = currentViewId;
  select.addEventListener('change', () => { currentViewId = select.value; render(); });

  const fresh = document.getElementById('freshness-note');
  const asOf = DASHBOARD.data_as_of ? new Date(DASHBOARD.data_as_of).toLocaleDateString() : 'unknown';
  const gen = new Date(DASHBOARD.generated_at).toLocaleString();
  fresh.textContent = `Data as of ${asOf} · Generated ${gen} · Rebuild with: python dashboards/claude_html/generate.py`;

  render();
}
init();
</script>
</body>
</html>
"""


def main() -> None:
    if not WAREHOUSE_PATH.exists():
        raise SystemExit(f"warehouse not found at {WAREHOUSE_PATH} -- run `dbt build` first")

    sections = parse_config(CONFIG_PATH.read_text())

    con = duckdb.connect(str(WAREHOUSE_PATH), read_only=True)
    try:
        data_as_of = run_metrics(con, sections)
        views = build_views(con)
    finally:
        con.close()

    default_view = "holdings" if any(v["id"] == "holdings" for v in views) else views[0]["id"]

    payload = {
        "generated_at": datetime.now().isoformat(),
        "data_as_of": data_as_of.isoformat() if isinstance(data_as_of, (date, datetime)) else data_as_of,
        "views": views,
        "default_view": default_view,
        "sections": sections,
    }

    html = HTML_SHELL.replace("__TITLE__", "CFO Financial Health Dashboard")
    html = html.replace("__DASHBOARD_JSON__", json.dumps(payload))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(html)

    n_metrics = sum(len(s["metrics"]) for s in sections)
    n_errors = sum(1 for s in sections for m in s["metrics"] if m["error"])
    print(f"Wrote {OUTPUT_PATH} ({n_metrics} metrics across {len(sections)} sections, "
          f"{len(views)} views, {n_errors} query errors)")


if __name__ == "__main__":
    main()
