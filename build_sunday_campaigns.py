"""Assign Sunday-active couriers to 5 rain-campaign time slots (exclusive)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

_RP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_RP_DIR))
sys.path.insert(1, str(_RP_DIR.parent))
from dbx import DBX

from build_report import (
    CITY_NAME,
    END,
    START,
    aggregate_couriers,
    load_courier_ids,
)

OUT_DIR = Path(__file__).parent
OUT_JSON = OUT_DIR / "sunday_campaigns.json"

SUNDAY_POOL_EXCLUDE = {"no_weekend", "occasional_saturday"}

CAMPAIGN_SLOTS = [
    {
        "id": "campaign_1",
        "title": "Кампанія 1 · ранок",
        "time_label": "07:00–11:59",
        "hour_start": 7,
        "hour_end": 11,
    },
    {
        "id": "campaign_2",
        "title": "Кампанія 2 · обід старт",
        "time_label": "12:00–13:59",
        "hour_start": 12,
        "hour_end": 13,
    },
    {
        "id": "campaign_3",
        "title": "Кампанія 3 · день",
        "time_label": "14:00–17:59",
        "hour_start": 14,
        "hour_end": 17,
    },
    {
        "id": "campaign_4",
        "title": "Кампанія 4 · вечір",
        "time_label": "18:00–20:59",
        "hour_start": 18,
        "hour_end": 20,
    },
    {
        "id": "campaign_5",
        "title": "Кампанія 5 · пізній вечір",
        "time_label": "21:00–23:59",
        "hour_start": 21,
        "hour_end": 23,
    },
]


def hour_to_slot(h: int) -> str | None:
    for slot in CAMPAIGN_SLOTS:
        if slot["hour_start"] <= h <= slot["hour_end"]:
            return slot["id"]
    return None


def fetch_sunday_hourly_deliveries(dbx: DBX, courier_ids: set[int]) -> pd.DataFrame:
    """Per courier × hour delivery counts on Sundays."""
    q = f"""
    SELECT
      courier_id,
      HOUR(order_created_at_local) AS hour,
      COUNT(*) AS deliveries
    FROM ng_delivery_spark.fact_order_delivery
    WHERE city_name = '{CITY_NAME}'
      AND order_created_date BETWEEN '{START}' AND '{END}'
      AND order_state = 'delivered'
      AND dayofweek(order_created_date) = 1
      AND courier_id IS NOT NULL
    GROUP BY courier_id, HOUR(order_created_at_local)
    """
    df = dbx.query(q)
    return df[df["courier_id"].isin(courier_ids)].copy()


def assign_primary_slot(hourly: pd.DataFrame, courier_id: int) -> tuple[str, str]:
    """Pick slot with most Sunday deliveries; tie-break by median hour."""
    sub = hourly[hourly["courier_id"] == courier_id]
    if sub.empty:
        return "campaign_unassigned", "no_sunday_deliveries"

    sub = sub.copy()
    sub["slot"] = sub["hour"].astype(int).map(hour_to_slot)
    sub = sub.dropna(subset=["slot"])
    if sub.empty:
        return "campaign_unassigned", "hours_outside_slots"

    slot_counts = sub.groupby("slot")["deliveries"].sum()
    best = slot_counts.idxmax()
    if slot_counts.max() == slot_counts.min() and len(slot_counts) > 1:
        weighted = sum(int(r.hour) * int(r.deliveries) for r in sub.itertuples())
        total = int(sub["deliveries"].sum())
        median_h = weighted // max(total, 1)
        fallback = hour_to_slot(median_h)
        if fallback:
            best = fallback
    return best, "delivery_weighted"


def build_sunday_campaigns(couriers: pd.DataFrame, hourly: pd.DataFrame) -> dict:
    pool = couriers[~couriers["cohort"].isin(SUNDAY_POOL_EXCLUDE)].copy()
    pool = pool[
        (pool["sun_active_weeks"] >= 1) | (pool["sun_delivery_count"] > 0)
    ].copy()

    assignments = []
    for _, row in pool.iterrows():
        cid = int(row["courier_id"])
        if row["sun_delivery_count"] > 0 and not hourly[hourly["courier_id"] == cid].empty:
            slot_id, method = assign_primary_slot(hourly, cid)
        elif row["sun_active_weeks"] >= 1 and pd.notna(row.get("sun_min_hour")):
            lo, hi = int(row["sun_min_hour"]), int(row["sun_max_hour"])
            mid = (lo + hi) // 2
            slot_id = hour_to_slot(mid) or "campaign_unassigned"
            method = "online_window_midpoint"
        else:
            slot_id = "campaign_unassigned"
            method = "online_only_no_hour"

        assignments.append(
            {
                "courier_id": cid,
                "weekend_cohort": row["cohort"],
                "campaign_slot": slot_id,
                "assignment_method": method,
                "sun_delivery_window": row.get("sun_delivery_window"),
                "sun_active_weeks": int(row["sun_active_weeks"]),
            }
        )

    assign_df = pd.DataFrame(assignments)

    unassigned_mask = assign_df["campaign_slot"] == "campaign_unassigned"
    fallback_idx = assign_df.index[unassigned_mask]
    fallback_sorted = assign_df.loc[fallback_idx].sort_values("courier_id")
    slot_ids = [s["id"] for s in CAMPAIGN_SLOTS]
    for i, orig_idx in enumerate(fallback_sorted.index):
        assign_df.at[orig_idx, "campaign_slot"] = slot_ids[i % len(slot_ids)]
        assign_df.at[orig_idx, "assignment_method"] = "online_only_balanced"

    slot_defs = {s["id"]: s for s in CAMPAIGN_SLOTS}
    campaigns = []

    for slot in CAMPAIGN_SLOTS:
        sid = slot["id"]
        subset = assign_df[assign_df["campaign_slot"] == sid]
        campaigns.append(
            {
                "id": sid,
                "title": slot["title"],
                "time_label": slot["time_label"],
                "description": (
                    f"Курʼєри, у яких більшість неділечних доставок за останні "
                    f"4 неділі припадає на {slot['time_label']}. "
                    f"Кожен courier_id у рівно одній кампанії (без дублікатів)."
                ),
                "count": int(len(subset)),
                "courier_ids": subset["courier_id"].astype(int).tolist(),
                "summary": {
                    "from_regular_both": int(
                        (subset["weekend_cohort"] == "regular_both").sum()
                    ),
                    "from_regular_sunday": int(
                        (subset["weekend_cohort"] == "regular_sunday").sum()
                    ),
                    "from_mixed_occasional": int(
                        (subset["weekend_cohort"] == "mixed_occasional").sum()
                    ),
                    "from_occasional_sunday": int(
                        (subset["weekend_cohort"] == "occasional_sunday").sum()
                    ),
                    "delivery_based": int(
                        (subset["assignment_method"] == "delivery_weighted").sum()
                    ),
                    "online_only_balanced": int(
                        (subset["assignment_method"] == "online_only_balanced").sum()
                    ),
                },
            }
        )

    return {
        "meta": {
            "purpose": "5 кампаній на неділю під грозу — почергова активність по слотах",
            "pool_definition": (
                "Усі з попереднього звіту, хто мав онлайн або доставки в неділю "
                "(виключено no_weekend та occasional_saturday)."
            ),
            "assignment_rule": (
                "Один слот на курʼєра: слот з найбільшою кількістю доставок у неділю; "
                "якщо доставок немає (лише онлайн) — рівномірний розподіл між 5 слотами."
            ),
            "pool_size": int(len(pool)),
            "assigned_to_slots": int(len(assign_df)),
            "unassigned_count": 0,
            "period_label": f"{START} — {END}",
        },
        "campaign_order": [s["id"] for s in CAMPAIGN_SLOTS],
        "campaigns": campaigns,
    }


def main() -> None:
    courier_df = load_courier_ids()
    with DBX() as dbx:
        from build_report import fetch_daily, fetch_delivery_hours

        daily = fetch_daily(dbx)
        hours = fetch_delivery_hours(dbx)
        hourly = fetch_sunday_hourly_deliveries(dbx, set(courier_df["Courier ID"]))

    couriers = aggregate_couriers(courier_df, daily, hours)
    report = build_sunday_campaigns(couriers, hourly)
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUT_JSON}")
    print(f"Pool: {report['meta']['pool_size']}")
    for c in report["campaigns"]:
        print(f"  {c['id']} {c['time_label']}: {c['count']}")
    print(f"  unassigned: {report['meta'].get('unassigned_count', 0)}")


if __name__ == "__main__":
    main()
