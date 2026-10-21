"""Transform the local CNIG raw CSV into an Andalusia Silver GeoParquet."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import shape

from .common.paths import (
    MUNICIPALITY_BOUNDARIES_BRONZE_PATH,
    MUNICIPALITY_BOUNDARIES_FAILED_PATH,
    MUNICIPALITY_BOUNDARIES_SILVER_PATH,
)

LOGGER = logging.getLogger(__name__)
SOURCE_NAME = "IGN/CNIG BDDAE"
ANDALUSIA_PROVINCE_CODES = frozenset({"04", "11", "14", "18", "21", "23", "29", "41"})
REQUIRED_SOURCE_COLUMNS = [
    "cnig_national_code",
    "cnig_name",
    "ine_code",
    "geometry",
]
OUTPUT_COLUMNS = [
    "municipality_code",
    "cnig_national_code",
    "municipality_name",
    "geometry",
    "source",
    "loaded_at_utc",
]
FAILURE_COLUMN = "failure_reason"


def clean_municipality_boundaries(
    boundaries: gpd.GeoDataFrame,
    loaded_at_utc: str | pd.Timestamp | None = None,
    failed_output_path: Path | None = MUNICIPALITY_BOUNDARIES_FAILED_PATH,
) -> gpd.GeoDataFrame:
    """Clean Andalusian boundaries and save rejected source rows for review."""
    missing_columns = sorted(
        set(REQUIRED_SOURCE_COLUMNS).difference(boundaries.columns)
    )
    if missing_columns:
        raise ValueError(f"Missing required CNIG columns: {missing_columns}")
    if boundaries.crs is None:
        raise ValueError("CNIG boundaries must have a declared coordinate reference system.")

    normalized = boundaries.copy().reset_index(drop=True).to_crs("EPSG:4326")
    for column in ("cnig_national_code", "cnig_name", "ine_code"):
        normalized[column] = normalized[column].astype("string").str.strip()

    reasons = normalized.get(
        "_failure_reason",
        pd.Series(pd.NA, index=normalized.index, dtype="string"),
    ).astype("string").fillna("")
    geometry_parse_failed = reasons.isin(
        {"Missing geometry", "Invalid GeoJSON geometry"}
    )

    def add_failure(mask: pd.Series, reason: str) -> None:
        failed_rows = mask.fillna(False)
        previous = reasons.loc[failed_rows]
        reasons.loc[failed_rows] = previous.mask(
            previous.eq(""),
            reason,
        ).where(previous.eq(""), previous + "; " + reason)

    missing_values = {
        column: normalized[column].isna() | normalized[column].eq("")
        for column in ("cnig_national_code", "cnig_name", "ine_code")
    }
    valid_ine_codes = (
        ~missing_values["ine_code"]
        & normalized["ine_code"].str.fullmatch(r"\d{5}").fillna(False)
    )
    out_of_scope = (
        valid_ine_codes
        & ~normalized["ine_code"].str[:2].isin(ANDALUSIA_PROVINCE_CODES)
    )
    in_scope = ~out_of_scope

    for column, missing in missing_values.items():
        add_failure(in_scope & missing, f"Missing required value: {column}")

    invalid_ine_codes = ~normalized["ine_code"].str.fullmatch(r"\d{5}").fillna(False)
    invalid_cnig_codes = (
        ~normalized["cnig_national_code"].str.fullmatch(r"\d{11}").fillna(False)
    )
    add_failure(
        in_scope & ~missing_values["ine_code"] & invalid_ine_codes,
        "Invalid municipality code format; expected five digits",
    )
    add_failure(
        in_scope & ~missing_values["cnig_national_code"] & invalid_cnig_codes,
        "Invalid CNIG national code format; expected eleven digits",
    )
    valid_codes = (
        ~missing_values["ine_code"]
        & ~missing_values["cnig_national_code"]
        & ~invalid_ine_codes
        & ~invalid_cnig_codes
    )
    mismatched_codes = valid_codes & ~normalized["cnig_national_code"].str[-5:].eq(
        normalized["ine_code"]
    )
    add_failure(
        in_scope & mismatched_codes,
        "CNIG national code does not end with municipality code",
    )

    if not in_scope.any():
        raise ValueError("CNIG source contains no Andalusian municipalities.")

    geometry = normalized.geometry
    missing_geometry = geometry.isna() & ~geometry_parse_failed
    empty_geometry = geometry.is_empty.fillna(False)
    invalid_geometry = ~geometry.is_valid.fillna(False) & geometry.notna()
    wrong_geometry_type = (
        geometry.notna()
        & ~empty_geometry
        & geometry.geom_type.ne("MultiPolygon").fillna(True)
    )
    add_failure(in_scope & missing_geometry, "Missing geometry")
    add_failure(in_scope & empty_geometry, "Empty geometry")
    add_failure(in_scope & invalid_geometry, "Invalid geometry")
    add_failure(
        in_scope & wrong_geometry_type,
        "Geometry type is not MultiPolygon",
    )

    eligible = normalized.loc[in_scope].copy()
    eligible["_failure_reason"] = reasons.loc[in_scope]
    quality_valid = eligible["_failure_reason"].eq("")
    geometry_wkb = eligible.loc[quality_valid].geometry.to_wkb()
    duplicate_records = eligible.loc[quality_valid].assign(
        _geometry_wkb=geometry_wkb
    )
    duplicate_mask = duplicate_records.duplicated(
        subset=[
            "ine_code",
            "cnig_national_code",
            "cnig_name",
            "_geometry_wkb",
        ],
        keep="first",
    )
    duplicate_indices = duplicate_records.index[duplicate_mask]
    eligible.loc[duplicate_indices, "_failure_reason"] = "Exact duplicate record"

    unique_valid = eligible.loc[eligible["_failure_reason"].eq("")]
    conflicting_codes = unique_valid.loc[
        unique_valid["ine_code"].duplicated(keep=False),
        "ine_code",
    ].unique()
    conflicting_rows = (
        eligible["ine_code"].isin(conflicting_codes)
        & eligible["_failure_reason"].eq("")
    )
    if conflicting_rows.any():
        previous = eligible.loc[conflicting_rows, "_failure_reason"]
        eligible.loc[conflicting_rows, "_failure_reason"] = previous.mask(
            previous.eq(""),
            "Conflicting duplicate municipality code",
        ).where(
            previous.eq(""),
            previous + "; Conflicting duplicate municipality code",
        )

    rejected = eligible.loc[eligible["_failure_reason"].ne("")].copy()
    rejected = rejected.drop(
        columns=["_failure_reason", "_geometry_wkb"],
        errors="ignore",
    )
    rejected[FAILURE_COLUMN] = eligible.loc[
        eligible["_failure_reason"].ne(""),
        "_failure_reason",
    ]
    if "source" not in rejected.columns:
        rejected["source"] = SOURCE_NAME

    silver = eligible.loc[eligible["_failure_reason"].eq("")].copy()
    silver = silver.rename(
        columns={
            "ine_code": "municipality_code",
            "cnig_name": "municipality_name",
        }
    )
    silver = silver.drop(columns="_failure_reason", errors="ignore")

    timestamp = pd.to_datetime(
        datetime.now(timezone.utc) if loaded_at_utc is None else loaded_at_utc,
        utc=True,
    )
    silver["source"] = SOURCE_NAME
    silver["loaded_at_utc"] = timestamp
    silver = silver.loc[:, OUTPUT_COLUMNS].sort_values(
        "municipality_code",
        kind="stable",
    ).reset_index(drop=True)
    if failed_output_path is not None:
        failed_path = Path(failed_output_path)
        failed_path.parent.mkdir(parents=True, exist_ok=True)
        rejected.to_parquet(failed_path, index=False)
    LOGGER.info(
        "Validated %s municipality boundaries; rejected %s rows.",
        len(silver),
        len(rejected),
    )
    return silver


def cnig_csv_to_geodataframe(raw_boundaries: pd.DataFrame) -> gpd.GeoDataFrame:
    """Convert the raw CNIG CSV columns and GeoJSON geometries to a GeoDataFrame."""
    required_columns = {"nationalCode", "name", "geometry"}
    missing_columns = sorted(required_columns.difference(raw_boundaries.columns))
    if missing_columns:
        raise ValueError(f"Missing required CNIG CSV columns: {missing_columns}")

    source_rows = raw_boundaries.copy().reset_index(drop=True)
    geometry_values = source_rows["geometry"].astype("string").str.strip()
    parsed_geometries = []
    parse_reasons = pd.Series("", index=source_rows.index, dtype="string")
    for row_index, value in geometry_values.items():
        if pd.isna(value) or value == "":
            parsed_geometries.append(None)
            parse_reasons.loc[row_index] = "Missing geometry"
            continue
        try:
            geojson_geometry = json.loads(value)
            if geojson_geometry is None:
                parsed_geometries.append(None)
                parse_reasons.loc[row_index] = "Missing geometry"
            else:
                parsed_geometries.append(shape(geojson_geometry))
        except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
            parsed_geometries.append(None)
            parse_reasons.loc[row_index] = "Invalid GeoJSON geometry"

    source_rows["geometry_raw"] = geometry_values
    source_rows = source_rows.drop(columns="geometry")
    national_codes = source_rows["nationalCode"].astype("string").str.strip()
    source_rows["cnig_national_code"] = national_codes
    source_rows["cnig_name"] = source_rows["name"].astype("string").str.strip()
    source_rows["ine_code"] = national_codes.str[-5:]
    source_rows["_failure_reason"] = parse_reasons
    return gpd.GeoDataFrame(
        source_rows,
        geometry=parsed_geometries,
        crs="EPSG:4326",
    )


def clean_municipality_boundaries_from_csv(
    source_csv_path: Path = MUNICIPALITY_BOUNDARIES_BRONZE_PATH,
    output_path: Path = MUNICIPALITY_BOUNDARIES_SILVER_PATH,
    failed_output_path: Path | None = MUNICIPALITY_BOUNDARIES_FAILED_PATH,
) -> Path:
    """Read CNIG's raw CSV and create a local Silver GeoParquet."""
    source_csv_path = Path(source_csv_path)
    output_path = Path(output_path)
    if source_csv_path.resolve() == output_path.resolve():
        raise ValueError("The raw CSV and processed Parquet paths must be different.")
    if failed_output_path is not None and Path(failed_output_path).resolve() in {
        source_csv_path.resolve(),
        output_path.resolve(),
    }:
        raise ValueError("The rejected output path must differ from raw and Silver paths.")

    raw_boundaries = pd.read_csv(
        source_csv_path,
        dtype="string",
        keep_default_na=False,
    )
    source_boundaries = cnig_csv_to_geodataframe(raw_boundaries)
    silver_boundaries = clean_municipality_boundaries(
        source_boundaries,
        failed_output_path=failed_output_path,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    silver_boundaries.to_parquet(
        output_path,
        index=False,
        compression="snappy",
    )

    LOGGER.info(
        "Saved %s Andalusian municipality boundaries to %s.",
        len(silver_boundaries),
        output_path,
    )
    return output_path
