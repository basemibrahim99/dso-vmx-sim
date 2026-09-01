"""
Synthetic multi-location dental group (DSO) data generator.

Simulates a portfolio company the way a real one would hand off data to a
PE/VMX analyst: three separate systems that don't agree on identifiers,
formats, or cleanliness. All data is fully synthetic (SIM- prefixed IDs) --
no real patients, providers, or locations.

Sources produced (data/raw/):
  - scheduling_export.csv   (practice management / scheduling system)
  - billing_export.csv      (separate billing/claims system)
  - patient_records.csv     (separate patient records system)

Dimension references (data/raw/):
  - locations_reference.csv
  - providers_reference.csv
  - procedures_reference.csv

Causal structure is baked in on purpose (per-location "health" score drives
utilization, no-show rate, and patient churn) so downstream models have real
signal to recover -- not just noise.
"""

import csv
import random
from datetime import date, timedelta

import numpy as np
from faker import Faker

SEED = 42
random.seed(SEED)
np.random.seed(SEED)
fake = Faker("en_CA")
Faker.seed(SEED)

TODAY = date(2026, 8, 26)
SIM_START = TODAY - timedelta(days=3 * 365)

OUT_DIR = "data/raw"

PROVINCES = ["ON", "ON", "ON", "BC", "BC", "AB", "AB", "QC", "MB", "NS"]
REGIONS = {
    "ON": "Ontario", "BC": "British Columbia", "AB": "Alberta",
    "QC": "Quebec", "MB": "Manitoba", "NS": "Nova Scotia",
}
CITIES = {
    "ON": ["Toronto", "Ottawa", "Hamilton", "Mississauga"],
    "BC": ["Vancouver", "Surrey", "Kelowna"],
    "AB": ["Calgary", "Edmonton"],
    "QC": ["Montreal", "Quebec City"],
    "MB": ["Winnipeg"],
    "NS": ["Halifax"],
}

PROCEDURES = [
    # code, name, avg_price, avg_cost (supplies/lab), avg_duration_min
    ("D0120", "Periodic Checkup", 65, 12, 20),
    ("D1110", "Adult Cleaning", 110, 25, 45),
    ("D0274", "Bitewing X-Rays", 55, 8, 15),
    ("D2140", "Amalgam Filling - 1 surface", 165, 30, 30),
    ("D2391", "Composite Filling - 1 surface", 195, 35, 35),
    ("D2740", "Crown - Porcelain", 1250, 380, 60),
    ("D3310", "Root Canal - Anterior", 850, 210, 75),
    ("D7140", "Simple Extraction", 220, 40, 30),
    ("D9944", "Night Guard", 480, 140, 20),
    ("D6010", "Dental Implant", 3200, 1100, 90),
    ("D9972", "Teeth Whitening", 450, 60, 45),
    ("D4341", "Periodontal Scaling", 320, 45, 50),
]

# Relative frequency weights, aligned index-for-index with PROCEDURES.
# Routine care (checkups/cleanings/x-rays) dominates real dental visit
# volume; crowns/root canals are uncommon; implants are rare. Uniform
# random.sample() previously picked all 12 procedures equally often, which
# inflated blended revenue-per-minute far past real-world dental economics
# (a $3,200 implant as likely as a $65 checkup).
PROCEDURE_WEIGHTS = [30, 25, 20, 8, 8, 3, 2, 3, 2, 0.5, 3, 4]
_PROCEDURE_PROBS = np.array(PROCEDURE_WEIGHTS) / sum(PROCEDURE_WEIGHTS)

INSURANCE_TYPES = ["employer_ppo", "provincial_basic", "self_pay", "self_pay", "employer_ppo"]

N_LOCATIONS = 10


def gen_locations():
    """Location dimension. Each gets a hidden 'health' score (0.35-1.0) that
    drives utilization, no-show, and churn elsewhere -- this is the ground
    truth downstream models should be able to recover."""
    locations = []
    for i in range(1, N_LOCATIONS + 1):
        prov = PROVINCES[(i - 1) % len(PROVINCES)]
        city = random.choice(CITIES[prov])
        opened = fake.date_between(start_date=date(2014, 1, 1), end_date=date(2023, 1, 1))
        health = float(np.clip(np.random.normal(0.72, 0.16), 0.30, 1.0))
        chairs = random.randint(3, 8)
        code = f"{prov}-{i:02d}"
        # billing system stores the "display name" -- occasionally inconsistent casing/spacing
        display_name = f"{city} - {fake.street_name()}"
        locations.append({
            "location_id": f"SIM-LOC-{i:03d}",
            "store_code": code,               # used by scheduling system
            "display_name": display_name,     # used by billing system
            "city": city,
            "province": prov,
            "region": REGIONS[prov],
            "chairs": chairs,
            "opened_date": opened,            # kept as date object; isoformat()'d only at write time
            "_health": round(health, 3),      # ground truth, not exported to raw/ consumers
        })
    return locations


def gen_providers(locations):
    providers = []
    pid = 1
    for loc in locations:
        n_dentists = max(1, loc["chairs"] // 3)
        n_hygienists = loc["chairs"] - n_dentists
        for _ in range(n_dentists):
            providers.append({
                "provider_id": f"SIM-PROV-{pid:04d}",
                "location_id": loc["location_id"],
                "role": "dentist",
                "name": f"Dr. {fake.last_name()}",
                "hire_date": fake.date_between(start_date=loc["opened_date"], end_date=TODAY).isoformat(),
                "hourly_cost": round(np.random.uniform(85, 135), 2),
            })
            pid += 1
        for _ in range(max(1, n_hygienists)):
            providers.append({
                "provider_id": f"SIM-PROV-{pid:04d}",
                "location_id": loc["location_id"],
                "role": "hygienist",
                "name": f"{fake.first_name()} {fake.last_name()}",
                "hire_date": fake.date_between(start_date=loc["opened_date"], end_date=TODAY).isoformat(),
                "hourly_cost": round(np.random.uniform(38, 58), 2),
            })
            pid += 1
    return providers


def gen_patients(locations):
    """Each patient gets a churn_risk latent partly driven by their home
    location's health score. Churning patients get a synthetically widening
    gap between visits before dropping off entirely."""
    patients = []
    pid = 1
    for loc in locations:
        # Panel size scales with chair count so completed-visit volume can
        # actually fill assumed chair capacity (chairs x 8hr x 5day/week --
        # see sql/gold/location_week_utilization.sql). At ~1 completed
        # visit/patient/year (after accounting for churn/tenure ramp-up)
        # and ~49 minutes/visit (weighted toward routine care -- see
        # PROCEDURE_WEIGHTS), ~1,980 patients per chair targets roughly
        # 70-90% utilization at a healthy location. Kept a narrow +/-3%
        # spread deliberately -- a wider one would swamp the no-show-rate
        # signal (driven by _health below) as the dominant source of
        # utilization variance, which would defeat the point of the model.
        n_patients = int(loc["chairs"] * np.random.uniform(1920, 2040))
        for _ in range(n_patients):
            signup = fake.date_between(start_date=SIM_START, end_date=TODAY - timedelta(days=30))
            base_churn = np.clip(1.0 - loc["_health"] + np.random.normal(0, 0.15), 0.05, 0.95)
            patients.append({
                "patient_id": f"SIM-PAT-{pid:06d}",
                "home_location_id": loc["location_id"],
                "signup_date": signup.isoformat(),
                "insurance_type": random.choice(INSURANCE_TYPES),
                "_churn_risk": round(base_churn, 3),
            })
            pid += 1
    return patients


def gen_visit_history(patients, locations, providers):
    """Generates the underlying visit events, then fans them out into the
    three messy source exports (scheduling / billing / patient_records)."""
    loc_by_id = {l["location_id"]: l for l in locations}
    providers_by_loc = {}
    for p in providers:
        providers_by_loc.setdefault(p["location_id"], []).append(p)

    appt_rows, claim_rows, patient_record_rows = [], [], []
    appt_id, claim_id = 1, 1

    for patient in patients:
        loc = loc_by_id[patient["home_location_id"]]
        loc_providers = providers_by_loc[loc["location_id"]]
        churn_risk = patient["_churn_risk"]

        signup = date.fromisoformat(patient["signup_date"])
        recall_interval = int(np.random.normal(200, 40))
        recall_interval = max(90, recall_interval)

        # explicit churn event: higher churn_risk raises the probability the
        # patient stops visiting entirely at some point in the past, rather
        # than merely drifting. Kept probabilistic (not a hard threshold) so
        # it's a real prediction problem downstream, not a lookup.
        is_churned = random.random() < np.clip(churn_risk * 0.75, 0, 0.9)
        churn_date = None
        if is_churned:
            earliest_churn = signup + timedelta(days=recall_interval)
            latest_churn = TODAY - timedelta(days=30)
            if earliest_churn >= latest_churn:
                is_churned = False  # not enough tenure to have meaningfully churned yet
            else:
                span_days = (latest_churn - earliest_churn).days
                churn_date = earliest_churn + timedelta(days=random.randint(0, span_days))

        visit_date = signup + timedelta(days=random.randint(0, 30))
        last_visit = None
        end_date = churn_date if is_churned else TODAY
        while visit_date < end_date:
            provider = random.choice(loc_providers)
            no_show_prob = np.clip(0.05 + (1 - loc["_health"]) * 0.25, 0.03, 0.4)
            status = "no_show" if random.random() < no_show_prob else "completed"

            appt_rows.append({
                "appointment_id": f"SIM-APT-{appt_id:07d}",
                "location_code": loc["store_code"],
                "provider_id": provider["provider_id"],
                "patient_id": patient["patient_id"],
                "scheduled_date": visit_date.isoformat(),
                "duration_min": "" if status == "no_show" else None,
                "status": status,
            })

            if status == "completed":
                last_visit = visit_date
                n_procs = np.random.choice([1, 2, 3], p=[0.55, 0.35, 0.10])
                proc_indices = np.random.choice(
                    len(PROCEDURES), size=n_procs, replace=False, p=_PROCEDURE_PROBS
                )
                procs = [PROCEDURES[i] for i in proc_indices]
                total_duration = 0
                for code, name, price, cost, dur in procs:
                    total_duration += dur
                    billed = round(price * np.random.uniform(0.95, 1.05), 2)
                    is_ppo = patient["insurance_type"] == "employer_ppo"
                    denial_prob = 0.04 if is_ppo else 0.08
                    if patient["insurance_type"] == "self_pay":
                        insurance_status, paid = "self_pay", billed
                    elif random.random() < denial_prob:
                        insurance_status, paid = "denied", 0.0
                    else:
                        pay_ratio = np.random.uniform(0.7, 1.0)
                        insurance_status, paid = "paid", round(billed * pay_ratio, 2)

                    # billing system references location by display_name, not id/code
                    billing_location_name = loc["display_name"]
                    if random.random() < 0.03:  # occasional casing/spacing inconsistency
                        billing_location_name = billing_location_name.upper()

                    claim_rows.append({
                        "claim_id": f"SIM-CLM-{claim_id:07d}",
                        "location_name": billing_location_name,
                        # ~2% of claims missing patient_id -- simulate a walk-in / intake gap
                        "patient_id": patient["patient_id"] if random.random() > 0.02 else "",
                        "procedure_code": code,
                        "claim_date": visit_date.strftime("%m/%d/%Y"),  # different date format than scheduling
                        "billed_amount": billed,
                        "paid_amount": paid,
                        "insurance_status": insurance_status,
                    })
                    claim_id += 1

                    if random.random() < 0.015:  # ~1.5% duplicate-claim data entry error
                        dup = dict(claim_rows[-1])
                        dup["claim_id"] = f"SIM-CLM-{claim_id:07d}"
                        claim_rows.append(dup)
                        claim_id += 1

                appt_rows[-1]["duration_min"] = total_duration

            appt_id += 1
            gap_days = int(recall_interval * np.random.uniform(0.85, 1.15))
            visit_date = visit_date + timedelta(days=gap_days)

        recall_due = (last_visit + timedelta(days=recall_interval)) if last_visit else None
        patient_record_rows.append({
            "patient_id": patient["patient_id"],
            "location_id": loc["location_id"],
            "insurance_type": patient["insurance_type"],
            # patient_records system stores dates in ISO except for a legacy batch that's still MM/DD/YYYY
            "last_visit_date": (last_visit.isoformat() if last_visit else ""),
            "recall_due_date": (recall_due.isoformat() if recall_due else ""),
            "signup_date": patient["signup_date"],
        })

    return appt_rows, claim_rows, patient_record_rows


def write_csv(rows, path, fieldnames):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows):>7,} rows -> {path}")


def main():
    import os
    os.makedirs(OUT_DIR, exist_ok=True)

    locations = gen_locations()
    providers = gen_providers(locations)
    patients = gen_patients(locations)
    appt_rows, claim_rows, patient_record_rows = gen_visit_history(patients, locations, providers)

    write_csv(
        [{**{k: v for k, v in l.items() if not k.startswith("_")}, "opened_date": l["opened_date"].isoformat()}
         for l in locations],
        f"{OUT_DIR}/locations_reference.csv",
        ["location_id", "store_code", "display_name", "city", "province", "region", "chairs", "opened_date"],
    )
    write_csv(providers, f"{OUT_DIR}/providers_reference.csv",
              ["provider_id", "location_id", "role", "name", "hire_date", "hourly_cost"])
    write_csv(
        [{"procedure_code": c, "name": n, "avg_price": p, "avg_cost": co, "avg_duration_min": d}
         for c, n, p, co, d in PROCEDURES],
        f"{OUT_DIR}/procedures_reference.csv",
        ["procedure_code", "name", "avg_price", "avg_cost", "avg_duration_min"],
    )
    write_csv(appt_rows, f"{OUT_DIR}/scheduling_export.csv",
              ["appointment_id", "location_code", "provider_id", "patient_id", "scheduled_date", "duration_min", "status"])
    write_csv(claim_rows, f"{OUT_DIR}/billing_export.csv",
              ["claim_id", "location_name", "patient_id", "procedure_code", "claim_date", "billed_amount", "paid_amount", "insurance_status"])
    write_csv(patient_record_rows, f"{OUT_DIR}/patient_records.csv",
              ["patient_id", "location_id", "insurance_type", "last_visit_date", "recall_due_date", "signup_date"])

    # ground-truth file, kept separate from raw/ -- for validating models later, not for the pipeline to consume
    os.makedirs("data/ground_truth", exist_ok=True)
    write_csv(
        [{"location_id": l["location_id"], "health_score": l["_health"]} for l in locations],
        "data/ground_truth/location_health.csv",
        ["location_id", "health_score"],
    )
    write_csv(
        [{"patient_id": p["patient_id"], "churn_risk": p["_churn_risk"]} for p in patients],
        "data/ground_truth/patient_churn_risk.csv",
        ["patient_id", "churn_risk"],
    )
    print("\nDone. Raw (messy) exports are in data/raw/, ground truth for later validation is in data/ground_truth/.")


if __name__ == "__main__":
    main()
