"""
Exports clean, Tableau-ready CSVs from the models/gold layer.

Tableau Public's free desktop app connects to files, not live databases --
so this script is the bridge between the pipeline (Postgres) and the
dashboard (Tableau Public). All business logic (tiers, $ framing, risk
scores) is precomputed here / upstream in models/ -- Tableau should only
need to visualize, not calculate, keeping the dashboard's logic in one
place (the pipeline) instead of duplicated in the BI tool.
"""

import pandas as pd
import sys
sys.path.insert(0, "../models")
from db import get_engine

OUT_DIR = "data"


def export_location_scorecard(engine):
    df = pd.read_sql(
        """
        SELECT s.*, l.city, l.province, l.region
        FROM models.location_utilization_scorecard s
        JOIN silver.locations l ON l.location_id = s.location_id
        ORDER BY s.avg_utilization_pct
        """,
        engine,
    )
    df.to_csv(f"{OUT_DIR}/location_scorecard.csv", index=False)
    print(f"wrote {len(df):>7,} rows -> {OUT_DIR}/location_scorecard.csv")
    return df


def export_patient_churn_risk(engine):
    df = pd.read_sql(
        """
        SELECT c.*, l.city, l.province, l.region
        FROM models.patient_churn_risk c
        JOIN silver.locations l ON l.location_id = c.location_id
        """,
        engine,
    )
    df.to_csv(f"{OUT_DIR}/patient_churn_risk.csv", index=False)
    print(f"wrote {len(df):>7,} rows -> {OUT_DIR}/patient_churn_risk.csv")
    return df


def export_location_summary(scorecard: pd.DataFrame, churn: pd.DataFrame):
    """One row per location, combining both models -- the table the
    portfolio-overview KPI tiles and top-level chart should read from."""
    churn_agg = churn.groupby("location_id").agg(
        high_risk_patients=("tier", lambda s: (s == "high").sum()),
        total_patients=("patient_id", "count"),
        total_revenue_at_risk=("revenue_at_risk", "sum"),
    ).reset_index()

    summary = scorecard.merge(churn_agg, on="location_id", how="left")
    summary.to_csv(f"{OUT_DIR}/location_summary.csv", index=False)
    print(f"wrote {len(summary):>7,} rows -> {OUT_DIR}/location_summary.csv")
    return summary


def main():
    engine = get_engine()
    scorecard = export_location_scorecard(engine)
    churn = export_patient_churn_risk(engine)
    export_location_summary(scorecard, churn)


if __name__ == "__main__":
    main()
