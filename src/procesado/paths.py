"""Canonical paths for the Bronze, Silver, and failed processing tables."""

from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
RAW_DIR = DATA_DIR / "raw"
SILVER_DIR = DATA_DIR / "processed" / "silver"
FAILED_DIR = SILVER_DIR / "failed"

GYMS_BRONZE_PATH = RAW_DIR / "gyms_andalusia.csv"
GYMS_SILVER_PATH = SILVER_DIR / "gyms_andalusia.parquet"
GYMS_FAILED_PATH = FAILED_DIR / "gyms_failed.parquet"

POPULATION_BRONZE_PATH = RAW_DIR / "population_andalusia.csv"
POPULATION_SILVER_PATH = SILVER_DIR / "population_andalusia.parquet"
POPULATION_FAILED_PATH = FAILED_DIR / "population_failed.parquet"

INCOME_BRONZE_PATH = RAW_DIR / "income_andalusia.csv"
INCOME_SILVER_PATH = SILVER_DIR / "income_andalusia.parquet"
INCOME_FAILED_PATH = FAILED_DIR / "income_failed.parquet"
