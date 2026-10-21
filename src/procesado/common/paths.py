"""Canonical paths for the Bronze, Silver, and failed processing tables."""

from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
RAW_DIR = DATA_DIR / "raw"
SILVER_DIR = DATA_DIR / "processed" / "silver"
FAILED_DIR = SILVER_DIR / "failed"
GOLD_DIR = DATA_DIR / "processed" / "gold"
GOLD_TABLE_PATH = GOLD_DIR / "tabla_oro_municipios_andalucia.parquet"

MUNICIPALITY_BOUNDARIES_BRONZE_PATH = (
    RAW_DIR / "municipality_boundaries_andalusia.csv"
)
MUNICIPALITY_BOUNDARIES_SILVER_PATH = (
    SILVER_DIR / "limites_municipales_andalucia.parquet"
)
MUNICIPALITY_BOUNDARIES_FAILED_PATH = (
    FAILED_DIR / "limites_municipales_andalucia_failed.parquet"
)

GYMS_BRONZE_PATH = RAW_DIR / "gyms_andalusia.csv"
GYMS_SILVER_PATH = SILVER_DIR / "gyms_andalusia.parquet"
GYMS_WITH_MUNICIPALITY_SILVER_PATH = (
    SILVER_DIR / "gyms_with_municipality_andalusia.parquet"
)
GYMS_FAILED_PATH = FAILED_DIR / "gyms_failed.parquet"

POPULATION_BRONZE_PATH = RAW_DIR / "population_andalusia.csv"
POPULATION_SILVER_PATH = SILVER_DIR / "population_andalusia.parquet"
POPULATION_FAILED_PATH = FAILED_DIR / "population_failed.parquet"

INCOME_BRONZE_PATH = RAW_DIR / "income_andalusia.csv"
INCOME_SILVER_PATH = SILVER_DIR / "income_andalusia.parquet"
INCOME_FAILED_PATH = FAILED_DIR / "income_failed.parquet"
