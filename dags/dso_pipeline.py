"""
DSO VMX Simulator -- Phase 1 pipeline.

bronze (raw CSV load, no coercion)
  -> silver (typed, entity-resolved, deduped -- see sql/silver/*.sql)
  -> quality checks (fail loudly, not silently)
  -> gold (business-ready facts -- see sql/gold/*.sql)
  -> summary (row-count report across all three layers)

Manually triggered (schedule=None) -- this is a static synthetic snapshot,
not a live recurring pipeline.
"""

import logging
import os
import time
from datetime import datetime

import pandas as pd
import psycopg2
from sqlalchemy import create_engine, types as satypes

from airflow.decorators import dag, task
from airflow.models.baseoperator import cross_downstream

log = logging.getLogger(__name__)

DSO_CONN_STR = os.environ["DSO_CONN_STR"]
DSO_SQLALCHEMY_URI = DSO_CONN_STR.replace("postgresql://", "postgresql+psycopg2://")
DATA_DIR = "/opt/airflow/data/raw"
SQL_DIR = "/opt/airflow/sql"

BRONZE_FILES = {
    "locations_reference": "locations_reference.csv",
    "providers_reference": "providers_reference.csv",
    "procedures_reference": "procedures_reference.csv",
    "scheduling_export": "scheduling_export.csv",
    "billing_export": "billing_export.csv",
    "patient_records": "patient_records.csv",
}

# Sequential on purpose: appointments.sql and claims.sql both join against
# silver.locations, so locations must land before them. Simpler and safer
# to run the whole set in a fixed order than to model fine-grained
# cross-script dependencies for six scripts.
SILVER_SCRIPTS = [
    "silver/locations.sql",
    "silver/providers.sql",
    "silver/procedures.sql",
    "silver/appointments.sql",
    "silver/claims.sql",
    "silver/patients.sql",
]

GOLD_SCRIPTS = [
    "gold/location_week_utilization.sql",
    "gold/patient_recall_status.sql",
]

# name -> SQL returning a single violation count; check fails if count != 0
CHECKS = {
    "no_unresolved_scheduling_locations": """
        SELECT COUNT(*) FROM bronze.scheduling_export s
        LEFT JOIN silver.locations l ON l.store_code = s.location_code
        WHERE l.location_id IS NULL
    """,
    "no_unresolved_billing_locations": """
        SELECT COUNT(*) FROM bronze.billing_export b
        LEFT JOIN silver.locations l
            ON UPPER(TRIM(l.display_name)) = UPPER(TRIM(b.location_name))
        WHERE l.location_id IS NULL
    """,
    "no_duplicate_content_claims": """
        SELECT COUNT(*) FROM (
            SELECT patient_id, procedure_code, claim_date, billed_amount, location_id
            FROM silver.claims
            WHERE patient_id IS NOT NULL
            GROUP BY 1, 2, 3, 4, 5
            HAVING COUNT(*) > 1
        ) dupes
    """,
    "no_null_scheduled_dates": "SELECT COUNT(*) FROM silver.appointments WHERE scheduled_date IS NULL",
    "no_null_claim_dates": "SELECT COUNT(*) FROM silver.claims WHERE claim_date IS NULL",
}

# All tables that exist by the end of a full run, grouped by layer -- used
# only by the final summary task to print a row-count report.
SUMMARY_TABLES = {
    "bronze": list(BRONZE_FILES.keys()),
    "silver": [s.split("/")[-1].replace(".sql", "") for s in SILVER_SCRIPTS],
    "gold": [s.split("/")[-1].replace(".sql", "") for s in GOLD_SCRIPTS],
}


def get_conn():
    return psycopg2.connect(DSO_CONN_STR)


def table_row_count(schema: str, table: str) -> int:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {schema}.{table}")
            return cur.fetchone()[0]
    finally:
        conn.close()


def run_sql_file(relative_path: str):
    """Executes a silver/gold transform script and logs what it produced --
    which table, how many rows landed, and how long it took. Table name is
    inferred from the script's own naming convention (schema/table.sql),
    which every script under sql/silver and sql/gold already follows."""
    schema, filename = relative_path.split("/")
    table = filename.replace(".sql", "")

    with open(f"{SQL_DIR}/{relative_path}") as f:
        sql = f.read()

    log.info("Running %s -> target table %s.%s", relative_path, schema, table)
    start = time.perf_counter()
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql)
    finally:
        conn.close()
    elapsed = time.perf_counter() - start

    row_count = table_row_count(schema, table)
    log.info("%s.%s: %s rows written in %.2fs", schema, table, f"{row_count:,}", elapsed)


@dag(
    schedule=None,
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["dso-vmx-sim"],
)
def dso_pipeline():

    @task
    def create_schemas():
        conn = get_conn()
        try:
            with conn:
                with conn.cursor() as cur:
                    for schema in ("bronze", "silver", "gold"):
                        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema};")
                        log.info("Ensured schema exists: %s", schema)
        finally:
            conn.close()

    @task
    def load_bronze(table: str, filename: str):
        # dtype=str + keep_default_na=False: bronze is a raw landing zone,
        # not a place to coerce types -- silver.*.sql owns all parsing/casting.
        path = f"{DATA_DIR}/{filename}"
        log.info("Loading %s -> bronze.%s", path, table)
        start = time.perf_counter()
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        log.info("Read %s rows, %s columns: %s", f"{len(df):,}", len(df.columns), list(df.columns))

        engine = create_engine(DSO_SQLALCHEMY_URI)
        try:
            df.to_sql(
                table,
                engine,
                schema="bronze",
                if_exists="replace",
                index=False,
                dtype={col: satypes.TEXT() for col in df.columns},
            )
        finally:
            engine.dispose()
        elapsed = time.perf_counter() - start
        log.info("bronze.%s: %s rows written in %.2fs", table, f"{len(df):,}", elapsed)
        return len(df)

    @task
    def run_silver(script: str):
        run_sql_file(script)

    @task
    def run_gold(script: str):
        run_sql_file(script)

    @task
    def run_quality_check(name: str, sql: str):
        log.info("Running quality check: %s", name)
        log.info("SQL:\n%s", sql.strip())
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                violations = cur.fetchone()[0]
        finally:
            conn.close()

        if violations != 0:
            log.error("Check FAILED: %s -- %s violating row(s)", name, violations)
            raise ValueError(f"Quality check failed: {name} -- {violations} violating row(s)")

        log.info("Check PASSED: %s -- 0 violations", name)
        return f"{name}: OK"

    @task(trigger_rule="all_done")
    def pipeline_summary():
        """Runs after gold builds regardless of whether every upstream task
        succeeded, so a partial/failed run still reports what did land --
        click this task's log for an at-a-glance view of the whole run."""
        lines = ["Pipeline row-count summary:", ""]
        for layer, tables in SUMMARY_TABLES.items():
            lines.append(f"  {layer}:")
            for table in tables:
                try:
                    count = table_row_count(layer, table)
                    lines.append(f"    {layer}.{table}: {count:,} rows")
                except Exception as e:
                    lines.append(f"    {layer}.{table}: ERROR ({e})")
        summary = "\n".join(lines)
        log.info(summary)
        return summary

    schemas = create_schemas()
    bronze_loads = [load_bronze.override(task_id=f"load_bronze_{t}")(t, f) for t, f in BRONZE_FILES.items()]
    schemas >> bronze_loads

    prev = bronze_loads
    silver_tasks = []
    for script in SILVER_SCRIPTS:
        name = script.split("/")[-1].replace(".sql", "")
        t = run_silver.override(task_id=f"silver_{name}")(script)
        prev >> t
        prev = t
        silver_tasks.append(t)

    check_tasks = [run_quality_check.override(task_id=f"check_{name}")(name, sql) for name, sql in CHECKS.items()]
    silver_tasks[-1] >> check_tasks

    gold_tasks = [
        run_gold.override(task_id=f"gold_{s.split('/')[-1].replace('.sql', '')}")(s) for s in GOLD_SCRIPTS
    ]
    cross_downstream(check_tasks, gold_tasks)

    gold_tasks >> pipeline_summary()


dso_pipeline()
