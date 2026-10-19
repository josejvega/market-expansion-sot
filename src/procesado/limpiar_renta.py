"""Cleaning helpers for the raw INE municipal income table."""

from __future__ import annotations

import pandas as pd

from src.ingesta.datos_poblacion.ine.common import ANDALUSIA_PROVINCES

from .common import split_ine_municipality_codes

SOURCE_COLUMNS = [
    "Municipios",
    "Distritos",
    "Secciones",
    "Indicadores de renta media",
    "Periodo",
    "Total",
    "source",
    "downloaded_at_utc",
]
INCOME_COLUMNS = [
    "municipality",
    "province",
    "province_code",
    "mean_net_income_per_person",
    "year",
    "source",
    "downloaded_at_utc",
]


def normalize_income_columns(income: pd.DataFrame) -> pd.DataFrame:
    """Normalize INE municipality identifiers, column names, and province names."""
    missing_columns = sorted(set(SOURCE_COLUMNS).difference(income.columns))
    if missing_columns:
        raise ValueError(f"Missing required income columns: {missing_columns}")

    municipality_fields = split_ine_municipality_codes(income["Municipios"])
    provinces = municipality_fields["province_code"].map(ANDALUSIA_PROVINCES)
    if provinces.isna().any():
        raise ValueError("Income data contains a municipality outside Andalusia.")

    return pd.DataFrame(
        {
            "municipality": municipality_fields["municipality"],
            "province": provinces,
            "province_code": municipality_fields["province_code"],
            "mean_net_income_per_person": income["Total"],
            "year": income["Periodo"],
            "source": income["source"],
            "downloaded_at_utc": income["downloaded_at_utc"],
        },
        index=income.index,
    ).loc[:, INCOME_COLUMNS]


def convert_income_values(income: pd.DataFrame) -> pd.DataFrame:
    """Convert INE's dotted thousands format to numeric income values."""
    converted = income.copy()
    converted["mean_net_income_per_person"] = pd.to_numeric(
        converted["mean_net_income_per_person"]
        .astype("string")
        .str.replace(".", "", regex=False),
        errors="raise",
    )
    return converted


def remove_duplicate_income_records(income: pd.DataFrame) -> pd.DataFrame:
    """Remove exact duplicate rows, preserving distinct municipal observations."""
    return income.drop_duplicates().reset_index(drop=True)


def sort_income_records(income: pd.DataFrame) -> pd.DataFrame:
    """Sort by province and municipality, with newest years first."""
    return income.sort_values(
        ["province", "municipality", "year"],
        ascending=[True, True, False],
        kind="stable",
    ).reset_index(drop=True)


def clean_income(income: pd.DataFrame) -> pd.DataFrame:
    """Normalize and clean an INE Bronze income table."""
    if set(INCOME_COLUMNS).issubset(income.columns):
        return income.loc[:, INCOME_COLUMNS].copy()

    normalized = normalize_income_columns(income)
    converted = convert_income_values(normalized)
    deduplicated = remove_duplicate_income_records(converted)
    return sort_income_records(deduplicated)
