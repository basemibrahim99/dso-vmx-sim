"""
Model 2: Patient Churn / Recall Risk (SDD 6.2).

Prospective design: the model is trained on a historical cutoff (12 months
before "today"), using only features knowable as of that cutoff, with the
label built from what actually happened in the 12 months *after* it. This
avoids a trap the first version fell into -- computing both features and
label as of "today" let the model see a patient's already-fully-elapsed
absence gap, which nearly tautologically predicts "already churned" without
learning anything prospective. Training on a past window and scoring the
current snapshot is how real churn models are deployed.

Note on the achievable ceiling: the generator's true churn_risk includes an
unobservable per-patient noise term, and the realized churn/no-churn outcome
is a single noisy coin-flip on top of that propensity (see generate_data.py
gen_patients / gen_visit_history). No feature set can fully recover an
individual's exact propensity from one noisy realization -- see
diagnose_ceiling() below for a quantified expectation of how far a model
can possibly get, so the final correlation can be judged against a
realistic bar instead of against 1.0.

Validated against data/ground_truth/patient_churn_risk.csv -- for grading
only, never used as an input here.
"""

import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.compose import ColumnTransformer

from db import get_engine

TODAY = pd.Timestamp("2026-08-26")  # matches generator TODAY / gold's fixed "as of" date
CUTOFF = TODAY - pd.Timedelta(days=365)
MIN_TENURE_BEFORE_SNAPSHOT_DAYS = 30  # matches the generator's initial-visit lag (signup -> first visit)

NUMERIC_FEATURES = ["tenure_days", "days_since_last_visit", "visit_count", "no_show_count", "avg_utilization_pct"]
CATEGORICAL_FEATURES = ["insurance_type", "location_tier"]


def load_patient_base(engine):
    return pd.read_sql(
        """
        SELECT p.patient_id, p.location_id, p.insurance_type, p.signup_date,
               u.avg_utilization_pct, u.tier AS location_tier
        FROM silver.patients p
        LEFT JOIN models.location_utilization_scorecard u ON u.location_id = p.location_id
        """,
        engine,
        parse_dates=["signup_date"],
    )


def load_appointments(engine):
    return pd.read_sql(
        "SELECT patient_id, scheduled_date, status FROM silver.appointments",
        engine,
        parse_dates=["scheduled_date"],
    )


def load_revenue_per_patient(engine):
    revenue_by_location = pd.read_sql(
        "SELECT location_id, SUM(billed_amount) AS total_billed FROM silver.claims GROUP BY location_id", engine
    )
    patients_by_location = pd.read_sql(
        "SELECT location_id, COUNT(*) AS n_patients FROM silver.patients GROUP BY location_id", engine
    )
    out = revenue_by_location.merge(patients_by_location, on="location_id")
    out["avg_annual_revenue_per_patient"] = out["total_billed"] / 3.0 / out["n_patients"]
    return out[["location_id", "avg_annual_revenue_per_patient"]]


def build_feature_label_frame(patient_base: pd.DataFrame, appts: pd.DataFrame, as_of: pd.Timestamp,
                               label_horizon_end: pd.Timestamp = None) -> pd.DataFrame:
    """
    Engagement features computed using ONLY appointment history up to
    `as_of` -- visit_count, days_since_last_visit, no_show_count.

    If `label_horizon_end` is given, also attaches the churn label: 1 if the
    patient had NO completed visit in (as_of, label_horizon_end]. The label
    is built from data strictly after `as_of`, so it can't leak into the
    features -- this is what makes the training set (as_of=CUTOFF,
    label_horizon_end=TODAY) a genuinely prospective task.

    If `label_horizon_end` is None, no label is attached -- used for the
    current scoring snapshot (as_of=TODAY), where the outcome is unknown.
    """
    before = appts[appts.scheduled_date <= as_of]
    completed_before = before[before.status == "completed"]

    agg = completed_before.groupby("patient_id").agg(
        visit_count=("scheduled_date", "count"),
        last_visit_date=("scheduled_date", "max"),
    )
    no_shows = before[before.status == "no_show"].groupby("patient_id").size().rename("no_show_count")

    # inner join: require >=1 completed visit before as_of -- an "established"
    # patient. Someone with no history yet has no meaningful engagement
    # signal to predict from.
    df = patient_base.merge(agg, on="patient_id", how="inner").merge(no_shows, on="patient_id", how="left")
    df["no_show_count"] = df["no_show_count"].fillna(0)
    df = df[df["signup_date"] <= as_of - pd.Timedelta(days=MIN_TENURE_BEFORE_SNAPSHOT_DAYS)].copy()

    df["tenure_days"] = (as_of - df["signup_date"]).dt.days
    df["days_since_last_visit"] = (as_of - df["last_visit_date"]).dt.days

    if label_horizon_end is not None:
        after = appts[
            (appts.scheduled_date > as_of) & (appts.scheduled_date <= label_horizon_end) & (appts.status == "completed")
        ]
        returned = set(after["patient_id"].unique())
        df["is_churned"] = (~df["patient_id"].isin(returned)).astype(int)

    return df


def build_pipeline(model):
    preprocess = ColumnTransformer([
        ("num", StandardScaler(), NUMERIC_FEATURES),
        ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
    ])
    return Pipeline([("preprocess", preprocess), ("model", model)])


def train_and_select(train_df: pd.DataFrame):
    X = train_df[NUMERIC_FEATURES + CATEGORICAL_FEATURES]
    y = train_df["is_churned"]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.25, stratify=y, random_state=42)

    candidates = {
        "logistic_regression": build_pipeline(LogisticRegression(max_iter=1000)),
        "random_forest": build_pipeline(RandomForestClassifier(n_estimators=200, max_depth=8, random_state=42)),
    }

    results = {}
    for name, pipe in candidates.items():
        pipe.fit(X_train, y_train)
        auc = roc_auc_score(y_test, pipe.predict_proba(X_test)[:, 1])
        results[name] = auc
        print(f"{name}: held-out AUC (prospective, 12mo-ahead outcome) = {auc:.3f}")

    winner = max(results, key=results.get)
    print(f"Selected: {winner}")

    final_pipe = candidates[winner]
    final_pipe.fit(X, y)  # refit on full training set
    return final_pipe, winner, results[winner]


def tier_for(score: float) -> str:
    if score >= 0.6:
        return "high"
    if score >= 0.3:
        return "med"
    return "low"


def score_and_frame(scoring_df: pd.DataFrame, model, revenue_per_patient: pd.DataFrame) -> pd.DataFrame:
    df = scoring_df.merge(revenue_per_patient, on="location_id", how="left")
    X = df[NUMERIC_FEATURES + CATEGORICAL_FEATURES]
    df["churn_risk_score"] = model.predict_proba(X)[:, 1]
    df["tier"] = df["churn_risk_score"].apply(tier_for)
    df["revenue_at_risk"] = round(df["churn_risk_score"] * df["avg_annual_revenue_per_patient"], 2)
    return df


def diagnose_ceiling(patient_base: pd.DataFrame):
    """
    The generator gives each patient churn_risk = location-driven component
    + unobservable individual noise (SD ~0.15, comparable to the
    location-driven component's own spread) -- then thins that continuous
    propensity through a single noisy Bernoulli draw to decide whether they
    actually churned. No model can recover the individual noise term from
    behavioral data; at best it can recover the location-driven share.
    This prints that share as a sanity bound: getting anywhere near it is a
    real result, expecting to reach 1.0 is not.
    """
    ground_truth = pd.read_csv("../data/ground_truth/patient_churn_risk.csv")
    m = ground_truth.merge(patient_base[["patient_id", "location_id"]], on="patient_id")
    location_means = m.groupby("location_id")["churn_risk"].transform("mean")
    location_explained_share = 1 - (m["churn_risk"] - location_means).var() / m["churn_risk"].var()
    print(f"Diagnostic: share of true churn_risk variance explained by location alone = {location_explained_share:.2f}")
    print("(This is roughly the ceiling any model can approach using location as a signal --")
    print(" the remainder is unobservable per-patient noise baked into the generator.)")


def main():
    engine = get_engine()
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS models;")

    patient_base = load_patient_base(engine)
    appts = load_appointments(engine)
    revenue_per_patient = load_revenue_per_patient(engine)

    diagnose_ceiling(patient_base)
    print()

    train_df = build_feature_label_frame(patient_base, appts, as_of=CUTOFF, label_horizon_end=TODAY)
    print(f"Training population (established as of {CUTOFF.date()}): {len(train_df):,}")
    print(f"Observed churn rate over the following 12 months: {train_df['is_churned'].mean():.1%}")
    print()

    model, winner_name, held_out_auc = train_and_select(train_df)
    print()

    scoring_df = build_feature_label_frame(patient_base, appts, as_of=TODAY, label_horizon_end=None)
    print(f"Current scoring population (established as of {TODAY.date()}): {len(scoring_df):,}")

    scored = score_and_frame(scoring_df, model, revenue_per_patient)

    ground_truth = pd.read_csv("../data/ground_truth/patient_churn_risk.csv")
    m = scored.merge(ground_truth, on="patient_id")
    corr = m["churn_risk_score"].corr(m["churn_risk"], method="spearman")
    auc_vs_ground_truth = roc_auc_score((m["churn_risk"] > 0.5).astype(int), m["churn_risk_score"])
    print(f"Validation (not used in training): Spearman(predicted, hidden churn_risk) = {corr:.3f}")
    print(f"Validation: AUC of predicted score vs. hidden churn_risk>0.5 = {auc_vs_ground_truth:.3f}")

    n_high_risk = (scored["tier"] == "high").sum()
    revenue_at_risk_total = scored.loc[scored["tier"] == "high", "revenue_at_risk"].sum()
    print(
        f"\n{n_high_risk:,} patients flagged high-risk, representing "
        f"~${revenue_at_risk_total:,.0f} in at-risk annual revenue -- recommend proactive recall outreach."
    )

    out_cols = ["patient_id", "location_id", "churn_risk_score", "tier", "revenue_at_risk",
                "days_since_last_visit", "visit_count", "no_show_count", "tenure_days"]
    scored[out_cols].to_sql("patient_churn_risk", engine, schema="models", if_exists="replace", index=False)
    print(f"\nWrote {len(scored)} rows -> models.patient_churn_risk (model={winner_name}, held-out AUC={held_out_auc:.3f})")


if __name__ == "__main__":
    main()
