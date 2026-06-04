"""Assign ALL Kyiv couriers to 5 Sunday rain-campaign time slots (exclusive)."""
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
        "title": "Кампанія 2 · обід",
        "time_label": "12:00–14:49",
        "hour_start": 12,
        "hour_end": 14,
    },
    {
        "id": "campaign_3",
        "title": "Кампанія 3 · день",
        "time_label": "15:00–17:59",
        "hour_start": 15,
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


def hour_to_slot(h: int) -> str:
    """Map delivery hour to campaign slot (inclusive ranges)."""
    if h < 7:
        return "campaign_1"
    for slot in CAMPAIGN_SLOTS:
        if slot["hour_start"] <= h <= slot["hour_end"]:
            return slot["id"]
    return "campaign_5"


def fetch_sunday_hourly_deliveries(dbx: DBX, courier_ids: set[int]) -> pd.DataFrame:
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


def sunday_peak_hour(sub: pd.DataFrame) -> int:
    """Typical Sunday delivery hour: mode hour, tie-break weighted average."""
    sub = sub.copy()
    sub["hour"] = sub["hour"].astype(int)
    sub["deliveries"] = sub["deliveries"].astype(int)
    max_del = sub["deliveries"].max()
    peaks = sub.loc[sub["deliveries"] == max_del, "hour"]
    if len(peaks) == 1:
        return int(peaks.iloc[0])
    weighted = (sub["hour"] * sub["deliveries"]).sum() / sub["deliveries"].sum()
    return int(round(weighted))


def assign_by_sunday_peak(
    hourly: pd.DataFrame, courier_id: int
) -> tuple[str, int, str] | tuple[None, None, None]:
    sub = hourly[hourly["courier_id"] == courier_id]
    if sub.empty:
        return None, None, None
    peak_h = sunday_peak_hour(sub)
    slot_id = hour_to_slot(peak_h)
    return slot_id, peak_h, "sunday_peak_hour"


def build_sunday_campaigns(couriers: pd.DataFrame, hourly: pd.DataFrame) -> dict:
    """All couriers in exactly one slot. Sunday DO history → mandatory hour slot."""
    pool = couriers.copy()
    slot_ids = [s["id"] for s in CAMPAIGN_SLOTS]

    assignments = []
    for _, row in pool.iterrows():
        cid = int(row["courier_id"])
        slot_id, peak_h, method = assign_by_sunday_peak(hourly, cid)
        if slot_id is None:
            slot_id = "pending_balanced"
            peak_h = None
            method = "no_sunday_history"

        assignments.append(
            {
                "courier_id": cid,
                "weekend_cohort": row["cohort"],
                "campaign_slot": slot_id,
                "assignment_method": method,
                "sunday_peak_hour": peak_h,
                "sun_delivery_window": row.get("sun_delivery_window"),
                "sun_active_weeks": int(row["sun_active_weeks"]),
            }
        )

    assign_df = pd.DataFrame(assignments)

    pending_mask = assign_df["campaign_slot"] == "pending_balanced"
    pending_idx = assign_df.index[pending_mask]
    pending_sorted = assign_df.loc[pending_idx].sort_values("courier_id")
    for i, orig_idx in enumerate(pending_sorted.index):
        assign_df.at[orig_idx, "campaign_slot"] = slot_ids[i % len(slot_ids)]
        assign_df.at[orig_idx, "assignment_method"] = "no_sunday_history_balanced"

    campaigns = []
    for slot in CAMPAIGN_SLOTS:
        sid = slot["id"]
        subset = assign_df[assign_df["campaign_slot"] == sid]
        peak_subset = subset[subset["assignment_method"] == "sunday_peak_hour"]
        campaigns.append(
            {
                "id": sid,
                "title": slot["title"],
                "time_label": slot["time_label"],
                "description": (
                    f"Усі активні курʼєри Kyiv, розбиті на 5 кампаній. "
                    f"Курʼєри з неділечними доставками потрапляють сюди за "
                    f"типовою годиною DO (напр. 18:00 → {slot['time_label']}). "
                    f"Решта — рівномірний розподіл без історії неділечних DO."
                ),
                "count": int(len(subset)),
                "courier_ids": subset["courier_id"].astype(int).tolist(),
                "summary": {
                    "sunday_peak_hour_assigned": int(len(peak_subset)),
                    "no_sunday_history_balanced": int(
                        (subset["assignment_method"] == "no_sunday_history_balanced").sum()
                    ),
                    "from_regular_both": int(
                        (subset["weekend_cohort"] == "regular_both").sum()
                    ),
                    "from_regular_sunday": int(
                        (subset["weekend_cohort"] == "regular_sunday").sum()
                    ),
                    "from_no_weekend": int(
                        (subset["weekend_cohort"] == "no_weekend").sum()
                    ),
                },
            }
        )

    peak_total = int(
        (assign_df["assignment_method"] == "sunday_peak_hour").sum()
    )
    balanced_total = int(
        (assign_df["assignment_method"] == "no_sunday_history_balanced").sum()
    )

    return {
        "meta": {
            "purpose": "5 кампаній на неділю під грозу — усі курʼєри Kyiv з W23 CSV",
            "pool_definition": (
                "Усі 13 167 active Kyiv couriers з W23 CSV (dim_courier verified)."
            ),
            "assignment_rule": (
                "1 courier_id = 1 кампанія. Якщо є доставки в неділю за 4 тижні — "
                "обовʼязково слот за типовою годиною DO (peak hour → "
                "07–11 / 12–14 / 15–17 / 18–20 / 21–23). Без неділечних DO — "
                "рівномірний розподіл між 5 слотами."
            ),
            "pool_size": int(len(pool)),
            "sunday_peak_hour_assigned": peak_total,
            "no_sunday_history_balanced": balanced_total,
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
    m = report["meta"]
    print(f"Pool: {m['pool_size']} | peak-hour: {m['sunday_peak_hour_assigned']} | balanced: {m['no_sunday_history_balanced']}")
    for c in report["campaigns"]:
        s = c["summary"]
        print(
            f"  {c['id']} {c['time_label']}: {c['count']} "
            f"(peak={s['sunday_peak_hour_assigned']}, rest={s['no_sunday_history_balanced']})"
        )


if __name__ == "__main__":
    main()
