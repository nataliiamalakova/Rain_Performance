"""Build Kyiv weekend courier cohort report from Databricks + W23 CSV list."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

_RP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_RP_DIR))
sys.path.insert(1, str(_RP_DIR.parent))
from dbx import DBX

CSV_PATH = Path(
    "/Users/nataliia.malakovabolt.eu/Downloads/W23 - Kyiv ENG.csv"
)
OUT_DIR = Path(__file__).parent
OUT_JSON = OUT_DIR / "report_data.json"
OUT_HTML = OUT_DIR / "index.html"

CITY_ID = 158
CITY_NAME = "Kyiv"
START = "2026-05-10"
END = "2026-06-01"
SATURDAYS = ["2026-05-10", "2026-05-17", "2026-05-24", "2026-05-31"]
SUNDAYS = ["2026-05-11", "2026-05-18", "2026-05-25", "2026-06-01"]
REGULAR_THRESHOLD = 3

COHORTS = [
    {
        "id": "regular_both",
        "title": "Usually both weekend days",
        "description": (
            "Online ≥3 of 4 Saturdays and ≥3 of 4 Sundays "
            "(courier_total_online_hours > 0)."
        ),
    },
    {
        "id": "regular_saturday",
        "title": "Usually Saturday only",
        "description": (
            "Online ≥3 of 4 Saturdays and ≤1 Sunday with online activity."
        ),
    },
    {
        "id": "regular_sunday",
        "title": "Usually Sunday only",
        "description": (
            "Online ≥3 of 4 Sundays and ≤1 Saturday with online activity."
        ),
    },
    {
        "id": "mixed_occasional",
        "title": "Occasionally both weekend days",
        "description": (
            "Online on both Saturday and Sunday, but no stable "
            "“regular” pattern (1–2 active weeks per day or irregular mix)."
        ),
    },
    {
        "id": "occasional_saturday",
        "title": "Occasionally Saturday only",
        "description": "1–2 Saturdays with online activity, no Sunday online.",
    },
    {
        "id": "occasional_sunday",
        "title": "Occasionally Sunday only",
        "description": "1–2 Sundays with online activity, no Saturday online.",
    },
    {
        "id": "no_weekend",
        "title": "Usually no weekend work",
        "description": (
            "0 Saturdays and 0 Sundays with courier_total_online_hours > 0 "
            "over the last 4 weekend weeks."
        ),
    },
]


def load_courier_ids() -> pd.DataFrame:
    df = pd.read_csv(CSV_PATH)
    df = df.dropna(subset=["Courier ID"]).copy()
    df["Courier ID"] = df["Courier ID"].astype(int)
    df = df[(df["Status"] == "active") & (df["City Name"] == CITY_NAME)]
    return df.drop_duplicates("Courier ID")


def fmt_hour(h) -> str | None:
    if pd.isna(h):
        return None
    return f"{int(h):02d}:00"


def fmt_window(min_h, max_h) -> str | None:
    if pd.isna(min_h) or pd.isna(max_h):
        return None
    lo, hi = int(min_h), int(max_h)
    return f"{lo:02d}:00–{hi:02d}:59"


def assign_cohort(sat_weeks: int, sun_weeks: int) -> str:
    if sat_weeks == 0 and sun_weeks == 0:
        return "no_weekend"
    if sat_weeks >= REGULAR_THRESHOLD and sun_weeks >= REGULAR_THRESHOLD:
        return "regular_both"
    if sat_weeks >= REGULAR_THRESHOLD and sun_weeks <= 1:
        return "regular_saturday"
    if sun_weeks >= REGULAR_THRESHOLD and sat_weeks <= 1:
        return "regular_sunday"
    if sat_weeks >= 1 and sun_weeks >= 1:
        return "mixed_occasional"
    if sat_weeks >= 1:
        return "occasional_saturday"
    if sun_weeks >= 1:
        return "occasional_sunday"
    return "no_weekend"


def fetch_daily(dbx: DBX) -> pd.DataFrame:
    q = f"""
    SELECT
      courier_id,
      metric_timestamp_partition AS dt,
      dayofweek(metric_timestamp_partition) AS dow,
      courier_total_online_hours AS online_hours,
      courier_delivered_orders_count AS delivered_orders
    FROM ng_delivery_spark.fact_courier_daily_v2
    WHERE city_id = {CITY_ID}
      AND metric_timestamp_partition BETWEEN '{START}' AND '{END}'
      AND dayofweek(metric_timestamp_partition) IN (1, 7)
    """
    return dbx.query(q)


def fetch_delivery_hours(dbx: DBX) -> pd.DataFrame:
    q = f"""
    SELECT
      courier_id,
      dayofweek(order_created_date) AS dow,
      MIN(HOUR(order_created_at_local)) AS min_hour,
      MAX(HOUR(order_created_at_local)) AS max_hour,
      COUNT(*) AS deliveries
    FROM ng_delivery_spark.fact_order_delivery
    WHERE city_name = '{CITY_NAME}'
      AND order_created_date BETWEEN '{START}' AND '{END}'
      AND order_state = 'delivered'
      AND dayofweek(order_created_date) IN (1, 7)
      AND courier_id IS NOT NULL
    GROUP BY courier_id, dayofweek(order_created_date)
    """
    return dbx.query(q)


def aggregate_couriers(
    courier_df: pd.DataFrame, daily: pd.DataFrame, hours: pd.DataFrame
) -> pd.DataFrame:
    ids = set(courier_df["Courier ID"].tolist())
    daily = daily[daily["courier_id"].isin(ids)].copy()
    hours = hours[hours["courier_id"].isin(ids)].copy()

    daily["online_hours"] = pd.to_numeric(daily["online_hours"], errors="coerce").fillna(0)
    daily["delivered_orders"] = pd.to_numeric(
        daily["delivered_orders"], errors="coerce"
    ).fillna(0)
    daily["active"] = daily["online_hours"] > 0

    sat = daily[daily["dow"] == 7]
    sun = daily[daily["dow"] == 1]

    sat_agg = (
        sat.groupby("courier_id")
        .agg(
            sat_active_weeks=("active", "sum"),
            sat_online_hours=("online_hours", "sum"),
            sat_delivered_orders=("delivered_orders", "sum"),
        )
        .reset_index()
    )
    sun_agg = (
        sun.groupby("courier_id")
        .agg(
            sun_active_weeks=("active", "sum"),
            sun_online_hours=("online_hours", "sum"),
            sun_delivered_orders=("delivered_orders", "sum"),
        )
        .reset_index()
    )

    sat_hours = hours[hours["dow"] == 7].groupby("courier_id").agg(
        sat_min_hour=("min_hour", "min"),
        sat_max_hour=("max_hour", "max"),
        sat_delivery_count=("deliveries", "sum"),
    )
    sun_hours = hours[hours["dow"] == 1].groupby("courier_id").agg(
        sun_min_hour=("min_hour", "min"),
        sun_max_hour=("max_hour", "max"),
        sun_delivery_count=("deliveries", "sum"),
    )

    base = courier_df.rename(columns={"Courier ID": "courier_id"})[
        ["courier_id", "Courier Engagement"]
    ].copy()

    out = (
        base.merge(sat_agg, on="courier_id", how="left")
        .merge(sun_agg, on="courier_id", how="left")
        .merge(sat_hours, on="courier_id", how="left")
        .merge(sun_hours, on="courier_id", how="left")
    )

    fill_cols = [
        "sat_active_weeks",
        "sun_active_weeks",
        "sat_online_hours",
        "sun_online_hours",
        "sat_delivered_orders",
        "sun_delivered_orders",
        "sat_delivery_count",
        "sun_delivery_count",
    ]
    for col in fill_cols:
        out[col] = out[col].fillna(0)

    out["sat_active_weeks"] = out["sat_active_weeks"].astype(int)
    out["sun_active_weeks"] = out["sun_active_weeks"].astype(int)
    out["cohort"] = out.apply(
        lambda r: assign_cohort(r["sat_active_weeks"], r["sun_active_weeks"]),
        axis=1,
    )
    out["sat_delivery_window"] = out.apply(
        lambda r: fmt_window(r["sat_min_hour"], r["sat_max_hour"])
        if r["sat_delivery_count"] > 0
        else None,
        axis=1,
    )
    out["sun_delivery_window"] = out.apply(
        lambda r: fmt_window(r["sun_min_hour"], r["sun_max_hour"])
        if r["sun_delivery_count"] > 0
        else None,
        axis=1,
    )
    return out


def build_report(couriers: pd.DataFrame) -> dict:
    cohort_defs = {c["id"]: c for c in COHORTS}
    cohort_payload = []

    for cohort in COHORTS:
        cid = cohort["id"]
        subset = couriers[couriers["cohort"] == cid]
        with_sat_do = subset[subset["sat_delivered_orders"] > 0]
        with_sun_do = subset[subset["sun_delivered_orders"] > 0]

        cohort_payload.append(
            {
                "id": cid,
                "title": cohort["title"],
                "description": cohort["description"],
                "count": int(len(subset)),
                "courier_ids": subset["courier_id"].astype(int).tolist(),
                "summary": {
                    "avg_sat_online_hours": round(
                        float(subset["sat_online_hours"].mean()), 2
                    ),
                    "avg_sun_online_hours": round(
                        float(subset["sun_online_hours"].mean()), 2
                    ),
                    "avg_sat_delivered_orders": round(
                        float(subset["sat_delivered_orders"].mean()), 2
                    ),
                    "avg_sun_delivered_orders": round(
                        float(subset["sun_delivered_orders"].mean()), 2
                    ),
                    "with_sat_deliveries": int(len(with_sat_do)),
                    "with_sun_deliveries": int(len(with_sun_do)),
                    "typical_sat_delivery_window": _typical_window(
                        with_sat_do, "sat_delivery_window"
                    ),
                    "typical_sun_delivery_window": _typical_window(
                        with_sun_do, "sun_delivery_window"
                    ),
                },
            }
        )

    return {
        "meta": {
            "city": CITY_NAME,
            "city_id": CITY_ID,
            "source_csv": str(CSV_PATH),
            "data_source": "ng_delivery_spark.fact_courier_daily_v2, fact_order_delivery",
            "period_label": f"{START} — {END}",
            "weekend_saturdays": SATURDAYS,
            "weekend_sundays": SUNDAYS,
            "regular_threshold_weeks": REGULAR_THRESHOLD,
            "total_couriers": int(len(couriers)),
            "active_definition": (
                "Couriers from CSV (Status=active, City=Kyiv), verified in "
                "dim_courier (status=active, city_id=158)."
            ),
            "online_active_definition": "courier_total_online_hours > 0",
            "delivery_window_note": (
                "Time window = min/max hour (HOUR(order_created_at_local)) "
                "of delivered orders on that weekday over 4 weekend weeks."
            ),
        },
        "cohorts": cohort_payload,
        "cohort_order": [c["id"] for c in COHORTS],
    }


def _typical_window(df: pd.DataFrame, col: str) -> str | None:
    windows = df[col].dropna()
    if windows.empty:
        return None
    top = windows.value_counts().head(3)
    parts = [f"{idx} ({cnt})" for idx, cnt in top.items()]
    return "; ".join(parts)


def embed_json_in_html(report: dict) -> None:
    html_path = OUT_DIR / "index.template.html"
    if not html_path.exists():
        raise FileNotFoundError(f"Missing template: {html_path}")
    template = html_path.read_text(encoding="utf-8")
    payload = json.dumps(report, ensure_ascii=False, separators=(",", ":"))
    html = template.replace("__REPORT_DATA__", payload)
    OUT_HTML.write_text(html, encoding="utf-8")


def main() -> None:
    from build_sunday_campaigns import (
        build_sunday_campaigns,
        fetch_sunday_hourly_deliveries,
    )

    courier_df = load_courier_ids()
    print(f"Loaded {len(courier_df)} active Kyiv couriers from CSV")

    ids = set(courier_df["Courier ID"].tolist())
    with DBX() as dbx:
        daily = fetch_daily(dbx)
        hours = fetch_delivery_hours(dbx)
        hourly = fetch_sunday_hourly_deliveries(dbx, ids)

    couriers = aggregate_couriers(courier_df, daily, hours)
    report = build_report(couriers)
    report["sunday_campaigns"] = build_sunday_campaigns(couriers, hourly)

    OUT_JSON.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    embed_json_in_html(report)

    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_HTML}")
    for c in report["cohorts"]:
        print(f"  {c['id']}: {c['count']}")


if __name__ == "__main__":
    main()
