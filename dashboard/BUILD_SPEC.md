# Tableau Public Build Spec

Everything here is precomputed — tiers, dollar figures, benchmarks — so
Tableau's job is purely visualization, not calculation. That's deliberate:
business logic lives in one place (the pipeline/models), not duplicated in
the BI layer. You shouldn't need more than a couple of trivial calculated
fields (noted below) anywhere in this build.

## 1. Connect the data

Open **Tableau Public Desktop** → Connect → Text File → select all three
CSVs in `dashboard/data/`:
- `location_scorecard.csv` (10 rows — one per location)
- `location_summary.csv` (10 rows — scorecard + churn rollup combined)
- `patient_churn_risk.csv` (89,536 rows — one per patient)

Relate `location_summary` and `patient_churn_risk` on `location_id` if you
want cross-filtering between the portfolio view and the patient list (Data
Source tab → drag second table in → Tableau auto-detects the relationship
on the shared column name).

## 2. Color encoding — use consistently across every sheet

The `tier` column already carries the business meaning — map it to color
**once** and reuse everywhere so a viewer learns the color language once:
- `green` → a real green (e.g. `#15803d`)
- `yellow` → amber, not pure yellow (e.g. `#b45309`) — pure yellow reads
  poorly on white
- `red` (present in `patient_churn_risk.tier`, not in location data — no
  location fell in the red band this run) → `#b91c1c`

Right-click the `tier` field in any sheet → Edit Colors → set this palette
once as a saved custom palette so every sheet that uses `tier` picks it up
automatically.

## 3. Sheets to build

### Sheet 1 — Portfolio KPI row
Four single-number tiles (Text tables or big Number cards), computed as
Tableau table calcs or just read straight off `location_summary`:
- **Locations below benchmark**: `COUNT(tier <> 'green')`
- **Total idle revenue opportunity**: `SUM(idle_revenue_opportunity_per_week) * 52` — label it "/year"
- **Patients at high churn risk**: `SUM(high_risk_patients)`
- **Total revenue at risk**: `SUM(total_revenue_at_risk)`

This is the "glance and know the state of the business" row — put it at
the top of the final dashboard.

### Sheet 2 — Utilization by location
Horizontal bar chart, `location_id` on rows (sorted by `avg_utilization_pct`
ascending — worst first, matches how an operator would scan it), `avg_utilization_pct` on columns, colored by `tier`.
Add a reference line at the `portfolio_benchmark` value (Analytics pane →
drag "Reference Line" → Constant → 0.745, or a calculated average) labeled
"Portfolio benchmark."
Tooltip: include `summary` (the pre-written sentence) so hovering a bar
reads like an analyst note, not just a number.

### Sheet 3 — Churn risk distribution
Histogram of `churn_risk_score` (Tableau: drag the field to Columns, right-click →
Create Bins, width ~0.05), colored by `tier`. Shows the shape of the risk
distribution, not just a single average.

### Sheet 4 — Revenue at risk by location
Bar chart: `location_id` on rows, `SUM(revenue_at_risk)` on columns (from
`patient_churn_risk`, aggregated), sorted descending. Pairs with Sheet 2 —
together they answer "which locations need attention, on both axes."

### Sheet 5 — Patient action list (the one ops would actually use)
A filterable table from `patient_churn_risk`: `patient_id`, `location_id`,
`churn_risk_score`, `revenue_at_risk`, `days_since_last_visit`,
`visit_count`. Filter to `tier = 'high'` by default (Filter shelf →
right-click → "Show Filter" so it's adjustable). Sort descending by
`revenue_at_risk` — highest-value at-risk patients surface first, which is
the actual outreach priority order.

## 4. Assemble the dashboard

New Dashboard → canvas size **1200×900** (fits most screens without
scrolling, matches the "read in under 2 minutes" success criterion from
the SDD):
- Top row: Sheet 1 (KPI tiles), full width, ~120px tall
- Middle: Sheet 2 and Sheet 4 side by side (utilization | revenue at risk)
- Below that: Sheet 3 (churn distribution), full width
- Bottom or a second tab: Sheet 5 (patient action list)

Add a **dashboard action** (Dashboard menu → Actions → Add Action →
Filter): clicking a bar in Sheet 2 or Sheet 4 filters Sheet 5 to that
location — turns "which location is worst" into "who do I call there" in
one click, which is the actual point of the dashboard.

## 5. Publish

File → Save to Tableau Public As... → sign in with your Tableau Public
account → this gives you the shareable public link (this is also why the
data had to be file-based, not a live Postgres connection — Tableau Public
publishes a snapshot, not a live query against your local machine).

**Before publishing**: double check every ID is `SIM-`-prefixed (it is, by
construction) and nothing in the `summary` text or column names could be
mistaken for a real practice — this data is synthetic but Tableau Public
is a public host by default.
