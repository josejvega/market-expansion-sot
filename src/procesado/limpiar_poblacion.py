"""Cleaning helpers for the raw INE population table."""

from __future__ import annotations

import pandas as pd

from src.ingesta.datos_poblacion.ine.common import ANDALUSIA_PROVINCES

from .common import split_ine_municipality_codes

SOURCE_COLUMNS = [
    "Provincias",
    "Municipios",
    "Sexo",
    "Edad",
    "Periodo",
    "Total",
    "source",
    "downloaded_at_utc",
]
POPULATION_COLUMNS = [
    "municipality",
    "province",
    "province_code",
    "age",
    "population",
    "year",
    "source",
    "downloaded_at_utc",
]
POPULATION_KEY_COLUMNS = [
    "municipality",
    "province",
    "province_code",
    "age",
    "year",
    "source",
    "downloaded_at_utc",
]


def filter_population_by_age(
    population: pd.DataFrame,
    minimum_age: int = 18,
    maximum_age: int = 50,
) -> pd.DataFrame:
    """Keep individual ages within the inclusive range, excluding age totals."""
    if minimum_age > maximum_age:
        raise ValueError("minimum_age must be less than or equal to maximum_age.")

    ages = population["Edad"].astype("string").str.extract(
        r"^\s*(\d+)(?:\s+años?)?\s*$",
        expand=False,
    )
    numeric_ages = pd.to_numeric(ages, errors="coerce")
    return population.loc[numeric_ages.between(minimum_age, maximum_age)].copy()


def keep_total_sex_records(population: pd.DataFrame) -> pd.DataFrame:
    """Keep the INE total-sex rows, not the separate sex breakdowns."""
    return population.loc[population["Sexo"].eq("Total")].copy()


def normalize_population_columns(population: pd.DataFrame) -> pd.DataFrame:
    """Rename INE fields and split municipality code, name, and province code."""
    missing_columns = sorted(set(SOURCE_COLUMNS).difference(population.columns))
    if missing_columns:
        raise ValueError(f"Missing required population columns: {missing_columns}")

    municipality_fields = split_ine_municipality_codes(population["Municipios"])
    provinces = municipality_fields["province_code"].map(ANDALUSIA_PROVINCES)
    if provinces.isna().any():
        raise ValueError("Population data contains a municipality outside Andalusia.")
    normalized = pd.DataFrame(
        {
            "municipality": municipality_fields["municipality"],
            "province": provinces,
            "province_code": municipality_fields["province_code"],
            "age": population["Edad"],
            "population": population["Total"],
            "year": population["Periodo"],
            "source": population["source"],
            "downloaded_at_utc": population["downloaded_at_utc"],
        },
        index=population.index,
    )
    return normalized.loc[:, POPULATION_COLUMNS]


def convert_population_values(population: pd.DataFrame) -> pd.DataFrame:
    """Convert age to integer and remove INE thousands separators from population."""
    converted = population.copy()
    age_values = pd.to_numeric(
        converted["age"].astype("string").str.extract(
            r"^\s*(\d+)(?:\s+años?)?\s*$",
            expand=False,
        ),
        errors="raise",
    )
    converted["age"] = age_values.astype("int64")
    converted["population"] = pd.to_numeric(
        converted["population"].astype("string").str.replace(
            ".",
            "",
            regex=False,
        ),
        errors="raise",
    )
    return converted


def aggregate_duplicate_population_records(
    population: pd.DataFrame,
) -> pd.DataFrame:
    """Sum duplicate municipality, age, year, and provenance records."""
    return (
        population.groupby(
            POPULATION_KEY_COLUMNS,
            as_index=False,
            dropna=False,
            sort=False,
        )["population"]
        .sum()
        .loc[:, POPULATION_COLUMNS]
    )


def sort_population_records(population: pd.DataFrame) -> pd.DataFrame:
    """Sort by province and municipality, newest year first, then ascending age."""
    return population.sort_values(
        ["province", "municipality", "year", "age"],
        ascending=[True, True, False, True],
        kind="stable",
    ).reset_index(drop=True)


def clean_population(population: pd.DataFrame) -> pd.DataFrame:
    """Apply the current population-cleaning steps to an INE Bronze table."""
    if set(POPULATION_COLUMNS).issubset(population.columns):
        return population.loc[:, POPULATION_COLUMNS].copy()

    age_filtered = filter_population_by_age(population)
    total_sex = keep_total_sex_records(age_filtered)
    normalized = normalize_population_columns(total_sex)
    converted = convert_population_values(normalized)
    aggregated = aggregate_duplicate_population_records(converted)
    return sort_population_records(aggregated)