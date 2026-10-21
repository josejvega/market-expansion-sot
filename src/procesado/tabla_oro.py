"""Build and persist the municipality-level Gold table."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from src.common.storage import get_storage_settings
from src.common.upload_to_s3 import upload_files_to_s3
from src.procesado.common.paths import GOLD_TABLE_PATH

GOLD_PREFIX = "gold"
GOLD_COLUMNS = [
    "municipality_code",
    "municipality_name",
    "province_code",
    "province",
    "population_year",
    "population_total",
    "population_18_50",
    "population_growth_start_year",
    "population_growth_pct",
    "income_year",
    "mean_net_income_per_person",
    "gyms_count",
    "other_sports_facilities_count",
]


def _require_columns(
    table: pd.DataFrame,
    table_name: str,
    required_columns: set[str],
) -> None:
    missing = sorted(required_columns.difference(table.columns))
    if missing:
        raise ValueError(f"Missing required {table_name} columns: {missing}")


def _normalize_municipality_years(
    table: pd.DataFrame,
    table_name: str,
    value_columns: list[str],
) -> pd.DataFrame:
    required_columns = {"municipality_code", "year", *value_columns}
    _require_columns(table, table_name, required_columns)

    normalized = table.loc[:, sorted(required_columns)].copy()
    normalized["municipality_code"] = (
        normalized["municipality_code"].astype("string").str.strip()
    )
    invalid_codes = (
        normalized["municipality_code"].isna()
        | ~normalized["municipality_code"].str.fullmatch(r"\d{5}").fillna(False)
    )
    if invalid_codes.any():
        raise ValueError(f"{table_name} contains invalid municipality codes.")

    year = pd.to_numeric(normalized["year"], errors="raise")
    if year.isna().any() or year.mod(1).ne(0).any():
        raise ValueError(f"{table_name} contains invalid years.")
    normalized["year"] = year.astype("int64")

    duplicate_keys = normalized.duplicated(
        subset=["municipality_code", "year"],
        keep=False,
    )
    if duplicate_keys.any():
        raise ValueError(
            f"{table_name} must have one row per municipality and year."
        )
    return normalized


def _latest_population_and_growth(population: pd.DataFrame) -> pd.DataFrame:
    normalized = _normalize_municipality_years(
        population,
        "population",
        [
            "municipality_name",
            "province_code",
            "province",
            "population_total",
            "population_18_50",
        ],
    )
    normalized["population_total"] = pd.to_numeric(
        normalized["population_total"],
        errors="raise",
    ).astype("int64")
    normalized["population_18_50"] = pd.to_numeric(
        normalized["population_18_50"],
        errors="raise",
    ).astype("int64")

    ordered = normalized.sort_values(
        ["municipality_code", "year"],
        kind="stable",
    )
    first_observation = ordered.drop_duplicates(
        "municipality_code",
        keep="first",
    ).loc[:, ["municipality_code", "year", "population_total"]].rename(
        columns={
            "year": "population_growth_start_year",
            "population_total": "population_first_total",
        }
    )
    latest = ordered.drop_duplicates(
        "municipality_code",
        keep="last",
    ).loc[
        :,
        [
            "municipality_code",
            "municipality_name",
            "province_code",
            "province",
            "year",
            "population_total",
            "population_18_50",
        ],
    ].rename(columns={"year": "population_year"})

    growth = first_observation.merge(
        latest.loc[:, ["municipality_code", "population_year", "population_total"]],
        on="municipality_code",
        validate="one_to_one",
    )
    has_growth_period = (
        growth["population_year"].gt(growth["population_growth_start_year"])
        & growth["population_first_total"].gt(0)
    )
    growth["population_growth_pct"] = (
        (
            growth["population_total"] - growth["population_first_total"]
        )
        .div(growth["population_first_total"])
        .mul(100)
        .where(has_growth_period)
    )
    return latest.merge(
        growth.loc[
            :,
            [
                "municipality_code",
                "population_growth_start_year",
                "population_growth_pct",
            ],
        ],
        on="municipality_code",
        validate="one_to_one",
    )


def _latest_income(income: pd.DataFrame) -> pd.DataFrame:
    normalized = _normalize_municipality_years(
        income,
        "income",
        ["mean_net_income_per_person"],
    )
    normalized["mean_net_income_per_person"] = pd.to_numeric(
        normalized["mean_net_income_per_person"],
        errors="raise",
    ).astype("int64")
    latest = normalized.sort_values(
        ["municipality_code", "year"],
        kind="stable",
    ).drop_duplicates("municipality_code", keep="last")
    return latest.loc[
        :,
        ["municipality_code", "year", "mean_net_income_per_person"],
    ].rename(columns={"year": "income_year"})


def _facility_counts(gyms: pd.DataFrame) -> pd.DataFrame:
    _require_columns(
        gyms,
        "municipality-assigned gym",
        {"municipality_code", "sport_centre_type"},
    )
    assigned = gyms.loc[:, ["municipality_code", "sport_centre_type"]].copy()
    assigned["municipality_code"] = (
        assigned["municipality_code"].astype("string").str.strip()
    )
    assigned["sport_centre_type"] = (
        assigned["sport_centre_type"].astype("string").str.strip()
    )
    missing_types = assigned["sport_centre_type"].isna() | assigned[
        "sport_centre_type"
    ].eq("")
    if missing_types.any():
        raise ValueError("Gym data contains missing sport_centre_type values.")

    assigned = assigned.loc[assigned["municipality_code"].notna()]
    assigned["_is_gym"] = assigned["sport_centre_type"].eq("gym")
    return (
        assigned.groupby("municipality_code", as_index=False, sort=False)
        .agg(
            gyms_count=("_is_gym", "sum"),
            other_sports_facilities_count=("_is_gym", lambda values: (~values).sum()),
        )
    )


def create_gold_table(
    population: pd.DataFrame,
    income: pd.DataFrame,
    gyms_with_municipality: pd.DataFrame,
) -> pd.DataFrame:
    """Create one municipality row with latest INE values and OSM counts."""
    latest_population = _latest_population_and_growth(population)
    latest_income = _latest_income(income)
    facility_counts = _facility_counts(gyms_with_municipality)

    gold = latest_population.merge(
        latest_income,
        on="municipality_code",
        how="left",
        validate="one_to_one",
    ).merge(
        facility_counts,
        on="municipality_code",
        how="left",
        validate="one_to_one",
    )
    gold["income_year"] = gold["income_year"].astype("Int64")
    gold["mean_net_income_per_person"] = gold[
        "mean_net_income_per_person"
    ].astype("Int64")
    gold["population_growth_start_year"] = gold[
        "population_growth_start_year"
    ].astype("int64")
    gold["population_growth_pct"] = gold["population_growth_pct"].astype("Float64")
    for column in ("gyms_count", "other_sports_facilities_count"):
        gold[column] = gold[column].fillna(0).astype("int64")

    return (
        gold.loc[:, GOLD_COLUMNS]
        .sort_values(["province_code", "municipality_code"], kind="stable")
        .reset_index(drop=True)
    )


def create_and_upload_gold_table(
    population: pd.DataFrame,
    income: pd.DataFrame,
    gyms_with_municipality: pd.DataFrame,
) -> pd.DataFrame:
    """Build Gold and persist locally, to S3, or to both destinations."""
    gold = create_gold_table(population, income, gyms_with_municipality)
    settings = get_storage_settings()

    def persist(output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        gold.to_parquet(output_path, index=False, compression="snappy")
        if settings.save_s3:
            upload_files_to_s3(
                [output_path],
                prefix=GOLD_PREFIX,
                bucket_name=settings.bucket_name,
                region_name=settings.region_name,
            )

    if settings.save_locally:
        persist(GOLD_TABLE_PATH)
    elif settings.save_s3:
        with TemporaryDirectory(prefix="market-expansion-gold-") as directory:
            persist(Path(directory) / GOLD_TABLE_PATH.name)

    return gold
