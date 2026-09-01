"""Shared DB connection helper for standalone model scripts run from the
host (outside the Airflow containers) against the dockerized warehouse."""

import os

from sqlalchemy import create_engine

# Host-mapped port (5434, not 5432 -- see docker-compose.yml comment on why).
DSO_URI = os.environ.get("DSO_URI", "postgresql+psycopg2://airflow:airflow@localhost:5434/dso")


def get_engine():
    return create_engine(DSO_URI)
