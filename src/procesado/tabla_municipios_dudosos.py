"""Identify municipalities whose OSM gym counts may be underreported."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd

from src.common.storage import get_storage_settings
from src.common.upload_to_s3 import upload_files_to_s3
from src.procesado.common.paths import DOUBTFUL_GYMS_TABLE_PATH

QUALITY_PREFIX = "processed/quality"
REFERENCE_MIN_POPULATION_18_50 = 5_000
MIN_EXPECTED_GYMS = 1.0
LOW_COVERAGE_THRESHOLD = 0.5
REVIEW_COLUMNS = [
    "municipality_code",
    "municipality_name",
    "province",
    "population_18_50",
    "gyms_count",
    "reference_gyms_per_10k_18_50",
    "expected_gyms",
    "observed_vs_expected_pct",
    "review_reason",
]
REVIEW_REASON = (
    "Posible infradetección en OSM: el recuento observado es inferior al "
    "50 % de la referencia estimada; revisar antes de tratarlo como dato confirmado."
)


def _require_columns(table: pd.DataFrame, required_columns: set[str]) -> None:
    missing = sorted(required_columns.difference(table.columns))
    if missing:
        raise ValueError(f"Missing required Gold columns: {missing}")


def create_doubtful_municipalities_table(gold: pd.DataFrame) -> pd.DataFrame:
    """Return municipalities with fewer than half the expected OSM gym count.

    The reference rate is the median observed gym density among municipalities
    with at least 5,000 residents aged 18–50 and at least one OSM gym.
    """
    required_columns = {
        "municipality_code",
        "municipality_name",
        "province",
        "population_18_50",
        "gyms_count",
    }
    _require_columns(gold, required_columns)
    municipalities = gold.loc[:, sorted(required_columns)].copy()

    codes = municipalities["municipality_code"].astype("string").str.strip()
    invalid_codes = (
        codes.isna() | ~codes.str.fullmatch(r"\d{5}").fillna(False)
    )
    if invalid_codes.any():
        raise ValueError("Gold contains invalid municipality codes.")
    if codes.duplicated().any():
        raise ValueError("Gold must contain one row per municipality.")
    municipalities["municipality_code"] = codes

    for column in ("population_18_50", "gyms_count"):
        values = pd.to_numeric(municipalities[column], errors="raise")
        if (
            values.isna().any()
            or not np.isfinite(values).all()
            or values.lt(0).any()
            or values.mod(1).ne(0).any()
        ):
            raise ValueError(f"Gold {column} must contain non-negative integers.")
        municipalities[column] = values.astype("int64")
    if municipalities["population_18_50"].eq(0).any():
        raise ValueError("Gold population_18_50 must be positive.")

    reference_municipalities = municipalities.loc[
        municipalities["population_18_50"].ge(REFERENCE_MIN_POPULATION_18_50)
        & municipalities["gyms_count"].gt(0)
    ]
    if reference_municipalities.empty:
        raise ValueError(
            "Cannot calculate the gym-density reference: no municipality has "
            f"at least {REFERENCE_MIN_POPULATION_18_50} residents aged 18–50 "
            "and at least one gym."
        )

    reference_rate = (
        reference_municipalities["gyms_count"]
        .div(reference_municipalities["population_18_50"])
        .mul(10_000)
        .median()
    )
    municipalities["expected_gyms"] = (
        reference_rate * municipalities["population_18_50"] / 10_000
    )
    is_doubtful = (
        municipalities["expected_gyms"].ge(MIN_EXPECTED_GYMS)
        & municipalities["gyms_count"].lt(
            LOW_COVERAGE_THRESHOLD * municipalities["expected_gyms"]
        )
    )
    review = municipalities.loc[is_doubtful].copy()
    review["reference_gyms_per_10k_18_50"] = reference_rate
    review["observed_vs_expected_pct"] = (
        review["gyms_count"].div(review["expected_gyms"]).mul(100)
    )
    review["review_reason"] = REVIEW_REASON
    return (
        review.loc[:, REVIEW_COLUMNS]
        .sort_values(
            ["observed_vs_expected_pct", "population_18_50", "municipality_code"],
            ascending=[True, False, True],
            kind="stable",
        )
        .reset_index(drop=True)
    )


def create_and_upload_doubtful_municipalities_table(
    gold: pd.DataFrame,
) -> pd.DataFrame:
    """Build and persist the OSM gym coverage review table."""
    review = create_doubtful_municipalities_table(gold)
    settings = get_storage_settings()

    def persist(output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        review.to_parquet(output_path, index=False, compression="snappy")
        if settings.save_s3:
            upload_files_to_s3(
                [output_path],
                prefix=QUALITY_PREFIX,
                bucket_name=settings.bucket_name,
                region_name=settings.region_name,
            )

    if settings.save_locally:
        persist(DOUBTFUL_GYMS_TABLE_PATH)
    elif settings.save_s3:
        with TemporaryDirectory(prefix="market-expansion-doubtful-gyms-") as directory:
            persist(Path(directory) / DOUBTFUL_GYMS_TABLE_PATH.name)

    return review
