"""Cleaning helpers for the raw OpenStreetMap gym table."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd

from .common.paths import GYMS_FAILED_PATH

_REQUIRED_SOURCE_COLUMNS = [
    "osm_type",
    "osm_id",
    "province_code",
    "province",
    "latitude",
    "longitude",
    "source",
    "downloaded_at_utc",
]
_OPTIONAL_SOURCE_COLUMNS = [
    "tag_name",
    "tag_leisure",
    "tag_sport",
]
# Address tags are omitted because postcode, street, and city appear in few rows.
# they appear in 400 of 4000 rows approx. and are not used in the current analysis.
_SOURCE_COLUMNS = _REQUIRED_SOURCE_COLUMNS + _OPTIONAL_SOURCE_COLUMNS
_OUTPUT_COLUMNS = [
    column for column in _SOURCE_COLUMNS if column != "tag_leisure"
] + ["sport_centre_type"]
_TEXT_COLUMNS = [
    "osm_id",
    "osm_type",
    "province_code",
    "province",
    "source",
    *_OPTIONAL_SOURCE_COLUMNS,
]


def _select_gym_columns(gyms: pd.DataFrame) -> pd.DataFrame:
    """Keep the source fields needed for the cleaned gym table."""
    missing_columns = sorted(
        set(_REQUIRED_SOURCE_COLUMNS).difference(gyms.columns)
    )
    if missing_columns:
        raise ValueError(f"Missing required gym columns: {missing_columns}")

    selected = gyms.copy()
    for column in _OPTIONAL_SOURCE_COLUMNS:
        if column not in selected.columns:
            selected[column] = pd.NA

    return selected.loc[:, _SOURCE_COLUMNS].copy()


def _convert_gym_types(gyms: pd.DataFrame) -> pd.DataFrame:
    """Convert gym identifiers, coordinates, text, and timestamps to clear types."""
    converted = gyms.copy()
    for column in ["latitude", "longitude"]:
        coordinate_values = converted[column].astype("string").replace(
            r"^\s*$",
            pd.NA,
            regex=True,
        )
        converted[column] = pd.to_numeric(
            coordinate_values,
            errors="raise",
        ).astype("Float64")

    for column in _TEXT_COLUMNS:
        converted[column] = converted[column].astype("string")

    downloaded_at_values = converted["downloaded_at_utc"].astype("string").replace(
        r"^\s*$",
        pd.NA,
        regex=True,
    )
    converted["downloaded_at_utc"] = pd.to_datetime(
        downloaded_at_values,
        utc=True,
        errors="raise",
    )
    return converted


def _normalize_gym_text(gyms: pd.DataFrame) -> pd.DataFrame:
    """Trim text fields and normalize the casing of standard identifiers."""
    normalized = gyms.copy()
    for column in _TEXT_COLUMNS:
        text_values = normalized[column].astype("string").str.strip()
        blank_values = text_values.eq("").fillna(False)
        normalized[column] = text_values.mask(blank_values, pd.NA)

    # OSM object types are lowercase, while province codes are uppercase.
    normalized["osm_type"] = normalized["osm_type"].str.lower()
    normalized["province_code"] = normalized["province_code"].str.upper()
    return normalized


def _remove_duplicate_gym_records(gyms: pd.DataFrame) -> pd.DataFrame:
    """Remove exact duplicates and keep the newest row for each OSM object."""
    unique_records = gyms.drop_duplicates()
    sorted_records = unique_records.sort_values(
        "downloaded_at_utc",
        ascending=True,
        na_position="first",
        kind="stable",
    )
    # Stable sorting keeps the last CSV occurrence when download times are tied.
    newest_records = sorted_records.drop_duplicates(
        subset=["osm_type", "osm_id"],
        keep="last",
    )
    return newest_records.sort_index(kind="stable").reset_index(drop=True)


def _validate_gym_province_consistency(gyms: pd.DataFrame) -> None:
    """Check that province codes and names map consistently within the table."""
    province_data = gyms.loc[:, ["province_code", "province"]].dropna().copy()
    province_data["province"] = province_data["province"].str.casefold()

    names_per_code = province_data.groupby("province_code")["province"].nunique()
    codes_per_name = province_data.groupby("province")["province_code"].nunique()
    conflicting_codes = names_per_code.loc[names_per_code > 1].index.tolist()
    conflicting_names = codes_per_name.loc[codes_per_name > 1].index.tolist()

    if conflicting_codes or conflicting_names:
        raise ValueError(
            "Province codes and names are inconsistent: "
            f"conflicting codes={conflicting_codes}, "
            f"conflicting names={conflicting_names}."
        )


def _remove_incomplete_gym_records(
    gyms: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Separate records without an OSM ID or coordinates for review."""
    required_value_columns = [
        "osm_type",
        "osm_id",
        "latitude",
        "longitude",
    ]
    incomplete_rows = gyms[required_value_columns].isna()
    failed_mask = incomplete_rows.any(axis=1)
    failed_records = gyms.loc[failed_mask].copy()
    failure_reasons = pd.Series("", index=failed_records.index, dtype="string")
    for column in required_value_columns:
        missing_value = incomplete_rows.loc[failed_mask, column]
        failure_reasons.loc[missing_value] = failure_reasons.loc[
            missing_value
        ].where(
            failure_reasons.loc[missing_value].eq(""),
            failure_reasons.loc[missing_value] + "; ",
        ) + f"Missing required value: {column}"
    failed_records["failure_reason"] = failure_reasons
    clean_records = gyms.loc[~failed_mask].copy()
    return clean_records, failed_records


def _validate_gym_coordinates(
    gyms: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Separate coordinates outside the valid latitude and longitude ranges."""
    valid_latitude = gyms["latitude"].between(-90, 90)
    valid_longitude = gyms["longitude"].between(-180, 180)
    invalid_coordinates = ~(valid_latitude & valid_longitude)

    clean_records = gyms.loc[~invalid_coordinates].copy()
    failed_records = gyms.loc[invalid_coordinates].copy()
    reasons = pd.Series("", index=failed_records.index, dtype="string")
    invalid_latitude = ~valid_latitude.loc[invalid_coordinates]
    invalid_longitude = ~valid_longitude.loc[invalid_coordinates]
    reasons.loc[invalid_latitude] = "Latitude outside valid range (-90 to 90)"
    reasons.loc[invalid_longitude] = "Longitude outside valid range (-180 to 180)"
    both_invalid = invalid_latitude & invalid_longitude
    reasons.loc[both_invalid] = (
        "Latitude outside valid range (-90 to 90); "
        "longitude outside valid range (-180 to 180)"
    )
    failed_records["failure_reason"] = reasons
    return clean_records, failed_records


def _save_failed_gym_records(
    failed_records: pd.DataFrame,
    output_path: Path | None,
) -> None:
    """Save rejected gym observations for review."""
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    failed_records.to_parquet(output_path, index=False)


def _create_gym_geometry(gyms: pd.DataFrame) -> gpd.GeoDataFrame:
    """Create point geometries from longitude and latitude in EPSG:4326."""
    gym_points = gpd.points_from_xy(
        gyms["longitude"],
        gyms["latitude"],
    )
    return gpd.GeoDataFrame(
        gyms.copy(),
        geometry=gym_points,
        crs="EPSG:4326",
    )


def _add_sport_centre_type(gyms: pd.DataFrame) -> pd.DataFrame:
    """Classify fitness centres separately from other sports facilities."""
    classified = gyms.copy()
    is_gym = classified["tag_leisure"].eq("fitness_centre")
    classified["sport_centre_type"] = "other_sport_facility"
    classified.loc[is_gym, "sport_centre_type"] = "gym"
    return classified.drop(columns="tag_leisure")


def clean_gyms(
    gyms: pd.DataFrame,
    failed_output_path: Path | None = GYMS_FAILED_PATH,
) -> gpd.GeoDataFrame:
    """Clean OSM records into one table of gyms and sports facilities."""
    selected = _select_gym_columns(gyms)
    converted = _convert_gym_types(selected)
    normalized = _normalize_gym_text(converted)
    deduplicated = _remove_duplicate_gym_records(normalized)
    _validate_gym_province_consistency(deduplicated)
    complete_records, incomplete_records = _remove_incomplete_gym_records(
        deduplicated
    )
    valid_records, invalid_coordinate_records = _validate_gym_coordinates(
        complete_records
    )
    failed_records = pd.concat(
        [incomplete_records, invalid_coordinate_records]
    ).sort_index(kind="stable")
    _save_failed_gym_records(
        failed_records.reset_index(drop=True),
        Path(failed_output_path) if failed_output_path is not None else None,
    )
    classified_records = _add_sport_centre_type(
        valid_records.reset_index(drop=True)
    )
    spatial_records = _create_gym_geometry(classified_records)
    return spatial_records.loc[
        :, _OUTPUT_COLUMNS + ["geometry"]
    ].reset_index(drop=True)