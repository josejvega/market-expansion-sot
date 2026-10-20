"""Cleaning helpers for the raw INE population table."""

from __future__ import annotations

import pandas as pd

from src.ingesta.datos_poblacion.ine.common import ANDALUSIA_PROVINCES

from .paths import POPULATION_FAILED_PATH

_SOURCE_COLUMNS = [
    "Provincias",
    "Municipios",
    "Sexo",
    "Edad",
    "Periodo",
    "Total",
    "source",
    "downloaded_at_utc",
]
_OUTPUT_COLUMNS = [
    "province_code",
    "province",
    "municipality_code",
    "municipality_name",
    "year",
    "population_total",
    "population_18_50",
    "source",
    "downloaded_at_utc",
]
_GROUP_COLUMNS = ["municipality_code", "year"]
_OBSERVATION_COLUMNS = ["municipality_code", "year", "age_label"]
_FAILURE_COLUMN = "failure_reason"


def _check_required_columns(population: pd.DataFrame) -> None:
    """Stop early when the input is missing a source column."""
    missing = sorted(set(_SOURCE_COLUMNS).difference(population.columns))
    if missing:
        raise ValueError(f"Missing required population columns: {missing}")


def _normalize_source_text(population: pd.DataFrame) -> pd.DataFrame:
    """Trim source text and treat blank cells as missing values."""
    cleaned = population.loc[:, _SOURCE_COLUMNS].copy().reset_index(drop=True)
    for column in _SOURCE_COLUMNS:
        values = cleaned[column].astype("string").str.strip()
        cleaned[column] = values.mask(values.eq(""), pd.NA)
    cleaned[_FAILURE_COLUMN] = pd.Series(
        pd.NA,
        index=cleaned.index,
        dtype="string",
    )
    return cleaned


def _add_failure_reason(
    population: pd.DataFrame,
    failed_rows: pd.Series,
    reason: str,
) -> pd.DataFrame:
    """Add a failure reason without replacing earlier validation messages."""
    if not failed_rows.any():
        return population

    cleaned = population.copy()
    previous_reasons = cleaned.loc[failed_rows, _FAILURE_COLUMN].fillna("")
    new_reasons = previous_reasons.mask(
        previous_reasons.eq(""),
        reason,
    ).where(
        previous_reasons.eq(""),
        previous_reasons + "; " + reason,
    )
    cleaned.loc[failed_rows, _FAILURE_COLUMN] = new_reasons
    return cleaned


def _keep_total_sex_rows(population: pd.DataFrame) -> pd.DataFrame:
    """Keep only INE rows that already combine men and women."""
    total_rows = population.loc[population["Sexo"].eq("Total")].copy()
    if total_rows.empty:
        raise ValueError("Population data does not contain total-sex rows.")
    return total_rows


def _mark_missing_values(population: pd.DataFrame) -> pd.DataFrame:
    """Mark rows that are missing a value needed for the population summary."""
    cleaned = population.copy()
    for column in _SOURCE_COLUMNS:
        missing = cleaned[column].isna()
        if missing.any():
            cleaned = _add_failure_reason(
                cleaned,
                missing,
                f"Missing required value: {column}",
            )
    return cleaned


def _add_municipality_details(population: pd.DataFrame) -> pd.DataFrame:
    """Get municipality name, province name, and codes from the INE fields."""
    cleaned = population.copy()
    municipality = cleaned["Municipios"].str.extract(
        r"^\s*(\d{5})\s+(.+?)\s*$"
    )
    source_province = cleaned["Provincias"].str.extract(
        r"^\s*(\d{2})\s+(.+?)\s*$"
    )
    cleaned["municipality_code"] = municipality[0]
    cleaned["municipality_name"] = municipality[1].str.strip()
    cleaned["province_code"] = municipality[0].str[:2]
    cleaned["province"] = cleaned["province_code"].map(ANDALUSIA_PROVINCES)

    bad_municipality = municipality[0].isna()
    cleaned = _add_failure_reason(
        cleaned,
        bad_municipality,
        "Invalid municipality code or name",
    )
    outside_andalusia = cleaned["province"].isna() & ~bad_municipality
    cleaned = _add_failure_reason(
        cleaned,
        outside_andalusia,
        "Municipality is outside Andalusia",
    )
    bad_province = source_province[0].isna() & ~bad_municipality
    cleaned = _add_failure_reason(
        cleaned,
        bad_province,
        "Invalid province code or name",
    )
    wrong_province_code = (
        source_province[0].notna()
        & cleaned["province_code"].notna()
        & source_province[0].ne(cleaned["province_code"])
    ).fillna(False)
    cleaned = _add_failure_reason(
        cleaned,
        wrong_province_code,
        "Province code does not match municipality code",
    )
    wrong_province_name = (
        source_province[1].notna()
        & cleaned["province"].notna()
        & source_province[1]
        .str.casefold()
        .ne(cleaned["province"].str.casefold())
    ).fillna(False)
    return _add_failure_reason(
        cleaned,
        wrong_province_name,
        "Province name does not match municipality code",
    )


def _convert_year(population: pd.DataFrame) -> pd.DataFrame:
    """Convert the INE period to an integer year."""
    cleaned = population.copy()
    year = pd.to_numeric(cleaned["Periodo"], errors="coerce")
    valid_year = year.notna() & year.mod(1).eq(0)
    cleaned["year"] = year.where(valid_year).astype("Int64")
    return _add_failure_reason(cleaned, ~valid_year, "Invalid year")


def _convert_age(population: pd.DataFrame) -> pd.DataFrame:
    """Convert each-age labels and keep the all-ages total as a separate row."""
    cleaned = population.copy()
    labels = cleaned["Edad"].astype("string").str.strip()
    ages = pd.to_numeric(
        labels.str.extract(r"^(\d+)\s+año(?:s)?$", expand=False),
        errors="coerce",
    )
    open_age_group = labels.str.fullmatch(
        r"\d+\s+y\s+más\s+año(?:s)?",
        case=False,
    ).fillna(False)
    all_ages = labels.eq("Todas las edades").fillna(False)
    valid_age = ages.notna() | open_age_group | all_ages

    cleaned["age_label"] = labels
    cleaned["age"] = ages.astype("Int64")
    return _add_failure_reason(cleaned, ~valid_age, "Invalid age label")


def _convert_population_count(population: pd.DataFrame) -> pd.DataFrame:
    """Convert INE population counts to non-negative integer values."""
    cleaned = population.copy()
    text = cleaned["Total"].astype("string")
    valid_format = text.str.fullmatch(
        r"(?:\d+|\d{1,3}(?:\.\d{3})+)"
    ).fillna(False)
    numbers = pd.to_numeric(
        text.str.replace(".", "", regex=False).where(valid_format),
        errors="coerce",
    )
    valid_count = numbers.notna() & numbers.ge(0) & numbers.mod(1).eq(0)
    cleaned["population"] = numbers.where(valid_count).astype("Int64")
    return _add_failure_reason(
        cleaned,
        ~valid_count,
        "Invalid population count",
    )


def _convert_download_timestamp(population: pd.DataFrame) -> pd.DataFrame:
    """Convert download timestamps to timezone-aware UTC."""
    cleaned = population.copy()
    timestamp = pd.to_datetime(
        cleaned["downloaded_at_utc"],
        format="ISO8601",
        utc=True,
        errors="coerce",
    )
    cleaned["downloaded_at_utc"] = timestamp
    return _add_failure_reason(
        cleaned,
        timestamp.isna(),
        "Invalid download timestamp",
    )


def _remove_duplicate_rows(population: pd.DataFrame) -> pd.DataFrame:
    """Reject repeated observations rather than counting them twice."""
    cleaned = population.copy()
    duplicate = cleaned.duplicated(
        subset=_OBSERVATION_COLUMNS + [
            "population",
            "source",
            "downloaded_at_utc",
        ],
        keep="first",
    )
    return _add_failure_reason(
        cleaned,
        duplicate,
        "Exact duplicate observation",
    )


def _remove_conflicting_observations(population: pd.DataFrame) -> pd.DataFrame:
    """Reject different values reported for the same municipality, year, and age."""
    cleaned = population.copy()
    usable = cleaned[_FAILURE_COLUMN].isna()
    rows = cleaned.loc[usable]
    conflict = rows.duplicated(subset=_OBSERVATION_COLUMNS, keep=False)
    conflicting_rows = pd.Series(False, index=cleaned.index)
    conflicting_rows.loc[conflict.index[conflict]] = True
    return _add_failure_reason(
        cleaned,
        conflicting_rows,
        "Conflicting observations for municipality, year, and age",
    )


def _remove_inconsistent_provenance(population: pd.DataFrame) -> pd.DataFrame:
    """Reject a municipality-year if its rows have different source metadata."""
    cleaned = population.copy()
    usable = cleaned[_FAILURE_COLUMN].isna()
    metadata = cleaned.loc[
        usable,
        _GROUP_COLUMNS + ["source", "downloaded_at_utc"],
    ]
    metadata_counts = metadata.groupby(_GROUP_COLUMNS)[
        ["source", "downloaded_at_utc"]
    ].nunique(dropna=False)
    inconsistent_groups = metadata_counts.index[
        metadata_counts.gt(1).any(axis=1)
    ]
    if len(inconsistent_groups):
        row_groups = pd.MultiIndex.from_frame(cleaned[_GROUP_COLUMNS])
        inconsistent_rows = row_groups.isin(inconsistent_groups)
        return _add_failure_reason(
            cleaned,
            pd.Series(inconsistent_rows, index=cleaned.index) & usable,
            "Inconsistent provenance for municipality and year",
        )
    return cleaned


def _add_incomplete_group_reasons(population: pd.DataFrame) -> pd.DataFrame:
    """Reject municipality-years missing a total or one of the ages 18 to 50."""
    cleaned = population.copy()
    usable = cleaned[_FAILURE_COLUMN].isna()
    records = cleaned.loc[usable]
    groups = records[_GROUP_COLUMNS].drop_duplicates()
    target_age_counts = (
        records.loc[records["age"].between(18, 50)]
        .groupby(_GROUP_COLUMNS)["age"]
        .nunique()
        .rename("target_age_count")
        .reset_index()
    )
    total_counts = (
        records.loc[records["age_label"].eq("Todas las edades")]
        .groupby(_GROUP_COLUMNS)
        .size()
        .rename("total_count")
        .reset_index()
    )
    quality = groups.merge(
        target_age_counts,
        on=_GROUP_COLUMNS,
        how="left",
    ).merge(
        total_counts,
        on=_GROUP_COLUMNS,
        how="left",
    )
    incomplete_groups = quality.loc[
        quality["target_age_count"].fillna(0).ne(33)
        | quality["total_count"].fillna(0).ne(1),
        _GROUP_COLUMNS,
    ]
    if incomplete_groups.empty:
        return cleaned

    failed_group_keys = pd.MultiIndex.from_frame(incomplete_groups)
    row_group_keys = pd.MultiIndex.from_frame(cleaned[_GROUP_COLUMNS])
    incomplete_rows = pd.Series(
        row_group_keys.isin(failed_group_keys),
        index=cleaned.index,
    ) & usable
    return _add_failure_reason(
        cleaned,
        incomplete_rows,
        "Missing required ages from 18 to 50 or all-ages total",
    )


def _separate_failed_rows(
    population: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Separate valid observations from rows with a recorded failure reason."""
    failed = population[_FAILURE_COLUMN].notna()
    return population.loc[~failed].copy(), population.loc[failed].copy()


def _build_population_summary(population: pd.DataFrame) -> pd.DataFrame:
    """Create one row per municipality and year from total-sex observations."""
    group_columns = _GROUP_COLUMNS + [
        "municipality_name",
        "province",
        "province_code",
    ]
    total_rows = population.loc[
        population["age_label"].eq("Todas las edades"),
        group_columns + ["population"],
    ].rename(columns={"population": "population_total"})
    target_rows = population.loc[
        population["age"].between(18, 50),
        _GROUP_COLUMNS + ["population"],
    ]
    target_population = target_rows.groupby(
        _GROUP_COLUMNS,
        as_index=False,
        sort=False,
    )["population"].sum()
    target_population = target_population.rename(
        columns={"population": "population_18_50"}
    )
    summary = total_rows.merge(
        target_population,
        on=_GROUP_COLUMNS,
        validate="one_to_one",
    )
    provenance = population[
        _GROUP_COLUMNS + ["source", "downloaded_at_utc"]
    ].drop_duplicates()
    summary = summary.merge(
        provenance,
        on=_GROUP_COLUMNS,
        validate="one_to_one",
    )
    summary = summary.loc[:, _OUTPUT_COLUMNS]
    for column in [
        "municipality_code",
        "municipality_name",
        "province",
        "province_code",
        "source",
    ]:
        summary[column] = summary[column].astype("string")
    summary["year"] = summary["year"].astype("int64")
    for column in ["population_total", "population_18_50"]:
        summary[column] = summary[column].astype("int64")
    summary["downloaded_at_utc"] = pd.to_datetime(
        summary["downloaded_at_utc"],
        format="ISO8601",
        utc=True,
        errors="raise",
    )
    return summary.sort_values(
        ["municipality_code", "year"],
        kind="stable",
    ).reset_index(drop=True)


def _save_failed_population_rows(failed: pd.DataFrame) -> None:
    """Save rejected source rows and their reason for review."""
    failed_rows = failed.loc[:, _SOURCE_COLUMNS + [_FAILURE_COLUMN]].copy()
    POPULATION_FAILED_PATH.parent.mkdir(parents=True, exist_ok=True)
    failed_rows.to_parquet(POPULATION_FAILED_PATH, index=False)


def _normalize_existing_summary(population: pd.DataFrame) -> pd.DataFrame:
    """Return an existing Silver table with its standard types and column order."""
    cleaned = population.loc[:, _OUTPUT_COLUMNS].copy()
    for column in [
        "municipality_code",
        "municipality_name",
        "province",
        "province_code",
        "source",
    ]:
        cleaned[column] = cleaned[column].astype("string").str.strip()
    for column in ["year", "population_total", "population_18_50"]:
        cleaned[column] = pd.to_numeric(cleaned[column], errors="raise").astype(
            "int64"
        )
    cleaned["downloaded_at_utc"] = pd.to_datetime(
        cleaned["downloaded_at_utc"],
        format="ISO8601",
        utc=True,
        errors="raise",
    )
    if cleaned.isna().any().any():
        raise ValueError("Clean population data contains missing values.")
    return cleaned.sort_values(
        ["municipality_code", "year"],
        kind="stable",
    ).reset_index(drop=True)


def clean_population(population: pd.DataFrame) -> pd.DataFrame:
    """Clean population data and save rejected source rows for review."""
    if set(_OUTPUT_COLUMNS).issubset(population.columns):
        return _normalize_existing_summary(population)

    _check_required_columns(population)
    cleaned = _normalize_source_text(population)
    cleaned = _keep_total_sex_rows(cleaned)
    cleaned = _mark_missing_values(cleaned)
    cleaned = _add_municipality_details(cleaned)
    cleaned = _convert_year(cleaned)
    cleaned = _convert_age(cleaned)
    cleaned = _convert_population_count(cleaned)
    cleaned = _convert_download_timestamp(cleaned)
    cleaned = _remove_duplicate_rows(cleaned)
    cleaned = _remove_conflicting_observations(cleaned)
    cleaned = _remove_inconsistent_provenance(cleaned)
    cleaned = _add_incomplete_group_reasons(cleaned)
    valid_rows, failed_rows = _separate_failed_rows(cleaned)
    summary = _build_population_summary(valid_rows)
    _save_failed_population_rows(failed_rows)
    return summary
