"""Cleaning helpers for the raw INE municipal income table."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.ingesta.datos_poblacion.ine.common import ANDALUSIA_PROVINCES

from .common.paths import INCOME_FAILED_PATH

_INDICATOR = "Renta neta media por persona"
_SOURCE_COLUMNS = [
    "Municipios",
    "Distritos",
    "Secciones",
    "Indicadores de renta media",
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
    "mean_net_income_per_person",
    "source",
    "downloaded_at_utc",
]
_FAILURE_COLUMN = "failure_reason"


def _check_required_columns(income: pd.DataFrame) -> None:
    """Stop early when the input is missing a source column."""
    missing = sorted(set(_SOURCE_COLUMNS).difference(income.columns))
    if missing:
        raise ValueError(f"Missing required income columns: {missing}")


def _select_municipal_income(income: pd.DataFrame) -> pd.DataFrame:
    """Keep municipality-level rows for the per-person income indicator."""
    municipal_rows = income.loc[
        income["Distritos"].astype("string").str.strip().eq("")
        & income["Secciones"].astype("string").str.strip().eq("")
    ].copy()
    selected = municipal_rows.loc[
        municipal_rows["Indicadores de renta media"]
        .astype("string")
        .str.strip()
        .eq(_INDICATOR)
    ].copy()
    if selected.empty:
        raise ValueError(f"Income data does not contain the '{_INDICATOR}' indicator.")
    return selected.reset_index(drop=True)


def _prepare_source_rows(income: pd.DataFrame) -> pd.DataFrame:
    """Trim source fields and initialize failure tracking."""
    prepared = income.loc[:, _SOURCE_COLUMNS].copy().reset_index(drop=True)
    for column in _SOURCE_COLUMNS:
        values = prepared[column].astype("string").str.strip()
        prepared[column] = values.mask(values.eq(""), pd.NA)
    prepared[_FAILURE_COLUMN] = pd.Series(
        pd.NA,
        index=prepared.index,
        dtype="string",
    )
    return prepared


def _add_failure_reason(
    income: pd.DataFrame,
    failed_rows: pd.Series,
    reason: str,
) -> pd.DataFrame:
    """Add a failure reason without losing earlier validation messages."""
    if not failed_rows.any():
        return income

    cleaned = income.copy()
    previous = cleaned.loc[failed_rows, _FAILURE_COLUMN].fillna("")
    cleaned.loc[failed_rows, _FAILURE_COLUMN] = previous.mask(
        previous.eq(""),
        reason,
    ).where(previous.eq(""), previous + "; " + reason)
    return cleaned


def _mark_missing_values(income: pd.DataFrame) -> pd.DataFrame:
    """Reject source rows missing data needed by the final table."""
    cleaned = income.copy()
    required_values = [
        "Municipios",
        "Indicadores de renta media",
        "Periodo",
        "Total",
        "source",
        "downloaded_at_utc",
    ]
    for column in required_values:
        cleaned = _add_failure_reason(
            cleaned,
            cleaned[column].isna(),
            f"Missing required value: {column}",
        )
    return cleaned


def _add_municipality_details(income: pd.DataFrame) -> pd.DataFrame:
    """Extract municipality and province details from the INE municipality field."""
    cleaned = income.copy()
    municipality = cleaned["Municipios"].str.extract(r"^(\d{5})\s+(.+?)$")
    cleaned["municipality_code"] = municipality[0]
    cleaned["municipality_name"] = municipality[1].str.strip()
    cleaned["province_code"] = municipality[0].str[:2]
    cleaned["province"] = cleaned["province_code"].map(ANDALUSIA_PROVINCES).astype(
        "string"
    )

    invalid_municipality = municipality[0].isna() | municipality[1].isna()
    cleaned = _add_failure_reason(
        cleaned,
        invalid_municipality,
        "Invalid municipality code or name",
    )
    outside_andalusia = cleaned["province"].isna() & ~invalid_municipality
    return _add_failure_reason(
        cleaned,
        outside_andalusia,
        "Municipality is outside Andalusia",
    )


def _convert_year(income: pd.DataFrame) -> pd.DataFrame:
    """Convert the INE period to an integer year."""
    cleaned = income.copy()
    year = pd.to_numeric(cleaned["Periodo"], errors="coerce")
    valid_year = year.notna() & year.mod(1).eq(0) & year.gt(0)
    cleaned["year"] = year.where(valid_year).astype("Int64")
    return _add_failure_reason(cleaned, ~valid_year, "Invalid year")


def _convert_income_values(income: pd.DataFrame) -> pd.DataFrame:
    """Convert INE's dotted thousands format to a non-negative numeric value."""
    cleaned = income.copy()
    text = cleaned["Total"].astype("string")
    valid_format = text.str.fullmatch(
        r"(?:\d+|\d{1,3}(?:\.\d{3})+)"
    ).fillna(False)
    amount = pd.to_numeric(
        text.str.replace(".", "", regex=False).where(valid_format),
        errors="coerce",
    )
    valid_amount = amount.notna() & amount.ge(0)
    cleaned["mean_net_income_per_person"] = amount.where(valid_amount).astype("Int64")
    return _add_failure_reason(
        cleaned,
        ~valid_amount,
        "Invalid income amount",
    )


def _convert_download_timestamp(income: pd.DataFrame) -> pd.DataFrame:
    """Convert download timestamps to timezone-aware UTC."""
    cleaned = income.copy()
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


def _reject_duplicate_rows(income: pd.DataFrame) -> pd.DataFrame:
    """Keep the first exact copy and mark subsequent copies as failed."""
    duplicate = income.duplicated(
        subset=_OUTPUT_COLUMNS,
        keep="first",
    )
    return _add_failure_reason(income, duplicate, "Exact duplicate observation")


def _reject_conflicting_records(income: pd.DataFrame) -> pd.DataFrame:
    """Reject every record when a municipality-year has conflicting values."""
    valid = income.loc[income[_FAILURE_COLUMN].isna()]
    duplicated_key = valid.duplicated(
        subset=["municipality_code", "year"],
        keep=False,
    )
    conflicting_indexes = valid.index[duplicated_key]
    conflicting = income.index.isin(conflicting_indexes)
    return _add_failure_reason(
        income,
        pd.Series(conflicting, index=income.index),
        "Conflicting records for municipality and year",
    )


def _save_failed_rows(
    income: pd.DataFrame,
    output_path: Path | None,
) -> None:
    """Write rejected source rows and their explanations to the failed table."""
    if output_path is None:
        return
    failed_columns = _SOURCE_COLUMNS + [_FAILURE_COLUMN]
    failed = income.loc[income[_FAILURE_COLUMN].notna(), failed_columns]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    failed.to_parquet(output_path, index=False)


def _sort_income(income: pd.DataFrame) -> pd.DataFrame:
    """Return income records in a stable province, municipality, and year order."""
    return income.sort_values(
        ["province_code", "municipality_code", "year"],
        kind="stable",
    ).reset_index(drop=True)


def _clean_source_income(income: pd.DataFrame) -> pd.DataFrame:
    """Validate source observations and separate valid rows from rejected rows."""
    _check_required_columns(income)
    selected = _select_municipal_income(income)
    cleaned = _prepare_source_rows(selected)
    cleaned = _mark_missing_values(cleaned)
    cleaned = _add_municipality_details(cleaned)
    cleaned = _convert_year(cleaned)
    cleaned = _convert_income_values(cleaned)
    cleaned = _convert_download_timestamp(cleaned)
    cleaned = _reject_duplicate_rows(cleaned)
    cleaned = _reject_conflicting_records(cleaned)
    return cleaned


def _normalize_clean_income(income: pd.DataFrame) -> pd.DataFrame:
    """Normalize already-clean rows so running the cleaner again is idempotent."""
    cleaned = income.loc[:, _OUTPUT_COLUMNS].copy()
    cleaned["province_code"] = cleaned["province_code"].astype("string")
    cleaned["province"] = cleaned["province"].astype("string")
    cleaned["municipality_code"] = cleaned["municipality_code"].astype("string")
    cleaned["municipality_name"] = cleaned["municipality_name"].astype("string")
    cleaned["year"] = pd.to_numeric(cleaned["year"], errors="raise").astype("int64")
    cleaned["mean_net_income_per_person"] = pd.to_numeric(
        cleaned["mean_net_income_per_person"],
        errors="raise",
    ).astype("int64")
    cleaned["source"] = cleaned["source"].astype("string")
    cleaned["downloaded_at_utc"] = pd.to_datetime(
        cleaned["downloaded_at_utc"],
        format="ISO8601",
        utc=True,
        errors="raise",
    )
    return _sort_income(cleaned.loc[:, _OUTPUT_COLUMNS])


def clean_income(
    income: pd.DataFrame,
    failed_output_path: Path | None = INCOME_FAILED_PATH,
) -> pd.DataFrame:
    """Return valid per-person income records and save rejected rows with reasons."""
    if set(_OUTPUT_COLUMNS).issubset(income.columns):
        _save_failed_rows(
            pd.DataFrame(columns=_SOURCE_COLUMNS + [_FAILURE_COLUMN]),
            Path(failed_output_path) if failed_output_path is not None else None,
        )
        return _normalize_clean_income(income)

    processed = _clean_source_income(income)
    _save_failed_rows(
        processed,
        Path(failed_output_path) if failed_output_path is not None else None,
    )
    valid = processed.loc[
        processed[_FAILURE_COLUMN].isna(),
        _OUTPUT_COLUMNS,
    ].copy()
    valid["year"] = valid["year"].astype("int64")
    valid["mean_net_income_per_person"] = valid[
        "mean_net_income_per_person"
    ].astype("int64")
    return _sort_income(valid)
