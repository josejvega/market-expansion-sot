"""Cleaning helpers for the raw OpenStreetMap gym table."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import geopandas as gpd
import pandas as pd

_GymOutputMode = Literal["only_gyms", "both", "sports_facilities"]
_GymCleaningOutput = (
    gpd.GeoDataFrame | tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]
)

_FAILED_GYMS_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "processed"
    / "silver"
    / "failed"
    / "gyms_failed.parquet"
)
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
_GYM_OUTPUT_COLUMNS = [
    column for column in _SOURCE_COLUMNS if column != "tag_sport"
]
_SPORTS_FACILITIES_COLUMNS = _SOURCE_COLUMNS.copy()
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
    complete_data = gyms.copy()
    required_value_columns = [
        "osm_type",
        "osm_id",
        "latitude",
        "longitude",
    ]
    incomplete_rows = complete_data[required_value_columns].isna().any(axis=1)
    failed_records = complete_data.loc[incomplete_rows].copy()
    clean_records = complete_data.loc[~incomplete_rows].copy()
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
    return clean_records, failed_records


def _save_failed_gym_records(failed_records: pd.DataFrame) -> None:
    """Save rejected gym observations for review."""
    _FAILED_GYMS_PATH.parent.mkdir(parents=True, exist_ok=True)
    failed_records.to_parquet(_FAILED_GYMS_PATH, index=False)


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


def _filter_fitness_centres(
    sports_facilities: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """Keep facilities tagged as fitness centres in OpenStreetMap."""
    fitness_centres = sports_facilities.loc[
        sports_facilities["tag_leisure"].eq("fitness_centre")
    ].copy()
    return gpd.GeoDataFrame(
        fitness_centres,
        geometry="geometry",
        crs=sports_facilities.crs,
    )


def clean_gyms(
    gyms: pd.DataFrame,
    output_mode: _GymOutputMode = "only_gyms",
) -> _GymCleaningOutput:
    """Clean OSM records and return gyms, sports facilities, or both."""
    valid_output_modes = {"only_gyms", "both", "sports_facilities"}
    if output_mode not in valid_output_modes:
        raise ValueError(
            "output_mode must be 'only_gyms', 'both', or 'sports_facilities'."
        )

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
    _save_failed_gym_records(failed_records.reset_index(drop=True))
    if output_mode == "only_gyms":
        fitness_centres = _filter_fitness_centres(
            _create_gym_geometry(valid_records.reset_index(drop=True))
        )
        return fitness_centres.loc[
            :, _GYM_OUTPUT_COLUMNS + ["geometry"]
        ].reset_index(drop=True)

    sports_facilities = _create_gym_geometry(
        valid_records.reset_index(drop=True)
    )
    if output_mode == "sports_facilities":
        return sports_facilities

    fitness_centres = _filter_fitness_centres(sports_facilities)
    gyms_output = fitness_centres.loc[
        :, _GYM_OUTPUT_COLUMNS + ["geometry"]
    ].reset_index(drop=True)
    sports_facilities_output = sports_facilities.loc[
        :, _SPORTS_FACILITIES_COLUMNS + ["geometry"]
    ].reset_index(drop=True)
    return gyms_output, sports_facilities_output