"""Baseline selection rules for the market expansion analysis.

This first baseline reads the population Silver table directly because it only
needs one cleaned feature. The final comparison should consume the integrated
Gold municipality table together with the model features.
"""

from __future__ import annotations

import pandas as pd

REQUIRED_COLUMNS = {
    "municipality_code",
    "municipality_name",
    "population_18_50",
    "year",
}
OUTPUT_COLUMNS = [
    "baseline_rank",
    "municipality_code",
    "municipality_name",
    "year",
    "population_18_50",
]


def select_top_municipalities(
    population: pd.DataFrame,
    top_n: int = 5,
    year: int | None = None,
) -> pd.DataFrame:
    """Select municipalities with the largest target population.

    This is the initial baseline implementation. When ``year`` is omitted, the
    latest year in the Silver population table is used. Ties are resolved by
    the municipality code to keep the baseline reproducible. Once the Gold
    municipality table exists, this rule should consume its equivalent feature
    instead of reading Silver directly.
    """
    if not isinstance(top_n, int) or isinstance(top_n, bool) or top_n < 1:
        raise ValueError("top_n must be a positive integer")

    missing = sorted(REQUIRED_COLUMNS.difference(population.columns))
    if missing:
        raise ValueError(f"Missing required population columns: {missing}")

    candidates = population.loc[:, sorted(REQUIRED_COLUMNS)].copy()
    candidates["year"] = pd.to_numeric(candidates["year"], errors="coerce")
    candidates["population_18_50"] = pd.to_numeric(
        candidates["population_18_50"],
        errors="coerce",
    )
    candidates["municipality_code"] = (
        candidates["municipality_code"].astype("string").str.strip()
    )
    candidates["municipality_name"] = (
        candidates["municipality_name"].astype("string").str.strip()
    )

    invalid = (
        candidates["year"].isna()
        | candidates["population_18_50"].isna()
        | candidates["municipality_code"].isna()
        | candidates["municipality_name"].isna()
    )
    if invalid.any():
        raise ValueError("Population baseline contains invalid required values")

    selected_year = int(candidates["year"].max()) if year is None else year
    if not isinstance(selected_year, int) or isinstance(selected_year, bool):
        raise ValueError("year must be an integer")

    candidates = candidates.loc[candidates["year"].eq(selected_year)].copy()
    if candidates.empty:
        raise ValueError(f"No population data found for year {selected_year}")

    duplicate_municipalities = candidates["municipality_code"].duplicated(
        keep=False
    )
    if duplicate_municipalities.any():
        raise ValueError(
            "Population baseline must contain one row per municipality and year"
        )

    result = candidates.sort_values(
        ["population_18_50", "municipality_code"],
        ascending=[False, True],
        kind="stable",
    ).head(top_n)
    result = result.loc[:, OUTPUT_COLUMNS[1:]].copy()
    result.insert(0, "baseline_rank", range(1, len(result) + 1))
    return result.reset_index(drop=True)
