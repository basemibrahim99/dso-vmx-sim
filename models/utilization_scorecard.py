"""
Model 1: Chair Utilization / OEE Scorecard (SDD 6.1).

Mostly business logic on top of gold.location_week_utilization, which
already computes utilization_pct in SQL -- this script adds the pieces a
raw utilization number doesn't give you on its own: a portfolio benchmark,
a tier, and the dollar translation (idle labor cost + recoverable revenue
opportunity) a non-technical stakeholder actually needs.

Validated against data/ground_truth/location_health.csv -- for grading
only, never used as an input here.
"""

import pandas as pd

from db import get_engine

# Tier thresholds relative to the portfolio benchmark (median utilization).
YELLOW_GAP = 0.03   # within 3pts of/above benchmark -> green
RED_GAP = 0.15       # more than 15pts below benchmark -> red; else yellow


def load_inputs(engine):
    weekly = pd.read_sql(
        """
        SELECT location_id, chairs, available_minutes,
               COUNT(*) AS n_weeks,
               AVG(utilization_pct) AS avg_utilization_pct,
               AVG(no_show_rate) AS avg_no_show_rate,
               SUM(completed_minutes) AS total_completed_minutes,
               AVG(completed_minutes) AS avg_completed_minutes_per_week
        FROM gold.location_week_utilization
        GROUP BY location_id, chairs, available_minutes
        """,
        engine,
    )
    provider_cost = pd.read_sql(
        """
        SELECT location_id, AVG(hourly_cost) AS blended_hourly_cost
        FROM silver.providers
        GROUP BY location_id
        """,
        engine,
    )
    revenue = pd.read_sql(
        """
        SELECT location_id, SUM(billed_amount) AS total_billed
        FROM silver.claims
        GROUP BY location_id
        """,
        engine,
    )
    return weekly, provider_cost, revenue


def tier_for(utilization_pct: float, benchmark: float) -> str:
    if utilization_pct >= benchmark - YELLOW_GAP:
        return "green"
    if utilization_pct >= benchmark - RED_GAP:
        return "yellow"
    return "red"


def build_scorecard(weekly, provider_cost, revenue):
    df = weekly.merge(provider_cost, on="location_id").merge(revenue, on="location_id")

    df["idle_minutes_per_week"] = df["available_minutes"] - df["avg_completed_minutes_per_week"]
    df["idle_labor_cost_per_week"] = round(df["idle_minutes_per_week"] / 60 * df["blended_hourly_cost"], 2)

    # blended $/minute of actually-delivered care, used to price idle capacity
    # at the same rate the location already earns -- not a hypothetical premium.
    df["revenue_per_completed_minute"] = df["total_billed"] / df["total_completed_minutes"]
    df["idle_revenue_opportunity_per_week"] = round(
        df["idle_minutes_per_week"] * df["revenue_per_completed_minute"], 2
    )

    benchmark = df["avg_utilization_pct"].median()
    df["portfolio_benchmark"] = round(benchmark, 3)
    df["tier"] = df["avg_utilization_pct"].apply(lambda u: tier_for(u, benchmark))

    df["avg_utilization_pct"] = round(df["avg_utilization_pct"], 3)

    df["summary"] = df.apply(
        lambda r: (
            f"{r.location_id} is operating at {r.avg_utilization_pct:.0%} utilization "
            f"vs. a {benchmark:.0%} portfolio benchmark ({r.tier}). "
            f"Idle capacity represents ~${r.idle_revenue_opportunity_per_week:,.0f}/week "
            f"(~${r.idle_revenue_opportunity_per_week * 52:,.0f}/year) in recoverable revenue, "
            f"plus ~${r.idle_labor_cost_per_week:,.0f}/week in provider cost sitting idle."
        ),
        axis=1,
    )

    return df[[
        "location_id", "chairs", "avg_utilization_pct", "portfolio_benchmark", "tier",
        "avg_no_show_rate", "idle_minutes_per_week", "idle_labor_cost_per_week",
        "idle_revenue_opportunity_per_week", "summary",
    ]].sort_values("avg_utilization_pct")


def validate_against_ground_truth(scorecard: pd.DataFrame):
    health = pd.read_csv("../data/ground_truth/location_health.csv")
    m = scorecard.merge(health, on="location_id")
    corr = m["avg_utilization_pct"].corr(m["health_score"], method="spearman")
    print(f"Validation (not used in scoring): Spearman(utilization, hidden health_score) = {corr:.3f}")
    return corr


def main():
    engine = get_engine()
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS models;")

    weekly, provider_cost, revenue = load_inputs(engine)
    scorecard = build_scorecard(weekly, provider_cost, revenue)

    print(scorecard[["location_id", "avg_utilization_pct", "tier", "idle_revenue_opportunity_per_week"]]
          .to_string(index=False))
    print()
    validate_against_ground_truth(scorecard)

    scorecard.to_sql("location_utilization_scorecard", engine, schema="models", if_exists="replace", index=False)
    print(f"\nWrote {len(scorecard)} rows -> models.location_utilization_scorecard")


if __name__ == "__main__":
    main()
