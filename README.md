# Rain Performance

Interactive report on **Kyiv courier weekend work patterns** (Saturday / Sunday) over the last 4 weeks.

**Live dashboard:** https://nataliiamalakova.github.io/Rain_Performance/

## Period

- **Saturdays:** 2026-05-10, 2026-05-17, 2026-05-24, 2026-05-31
- **Sundays:** 2026-05-11, 2026-05-18, 2026-05-25, 2026-06-01
- **Sample:** 13,167 active couriers from `W23 - Kyiv ENG.csv` (verified in `dim_courier`, city_id=158)

## Metrics

| Metric | Source |
|---|---|
| Courier Online Hours | `fact_courier_daily_v2.courier_total_online_hours` |
| Courier Delivered Orders | `fact_courier_daily_v2.courier_delivered_orders_count` |
| Delivery time window | `HOUR(order_created_at_local)` (min–max per Sat / Sun) |

**Active day** = `courier_total_online_hours > 0`.

**“Regular”** = online on ≥3 of 4 corresponding weekend days.

## Sunday · 5 storm campaigns (main view)

| Campaign | Time |
|---|---|
| 1 | 07:00–11:59 |
| 2 | 12:00–14:49 |
| 3 | 15:00–17:59 |
| 4 | 18:00–20:59 |
| 5 | 21:00–23:59 |

**Pool:** all **13,167** active Kyiv couriers from W23 CSV.

**Assignment:** one `courier_id` = one campaign.

- Sunday deliveries over 4 weeks → **mandatory** slot by typical DO peak hour (e.g. 18:00 → campaign 4).
- No Sunday DO history → even split across 5 slots.

## Weekend cohorts (collapsed section)

1. **Usually both weekend days**
2. **Usually Saturday only**
3. **Usually Sunday only**
4. **Occasionally both weekend days**
5. **Occasionally Saturday only**
6. **Occasionally Sunday only**
7. **Usually no weekend work**

## Files

- `index.html` — interactive report (CSV download per cohort / campaign)
- `report_data.json` — report data
- `build_report.py` — Databricks + CSV pipeline
- `build_sunday_campaigns.py` — Sunday campaign slot assignment

## Refresh

```bash
cd "/Users/nataliia.malakovabolt.eu/Downloads/Session with Jakub H./Rain_Performance"
../.venv/bin/python3 build_report.py
git push
```

Requires `.env` with Databricks token in the workspace root (see `dbx.py`).

## GitHub Pages

Live: **https://nataliiamalakova.github.io/Rain_Performance/** (branch `main`, root).
