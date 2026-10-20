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


def clean_municipality_boundaries(
    boundaries: gpd.GeoDataFrame,
    loaded_at_utc: str | pd.Timestamp | None = None,
) -> gpd.GeoDataFrame:
    """Normalize, validate, and retain Andalusian CNIG municipality boundaries."""
    missing_columns = sorted(
        set(REQUIRED_SOURCE_COLUMNS).difference(boundaries.columns)
    )
    if missing_columns:
        raise ValueError(f"Missing required CNIG columns: {missing_columns}")
    if boundaries.crs is None:
        raise ValueError("CNIG boundaries must have a declared coordinate reference system.")

    normalized = boundaries.loc[:, REQUIRED_SOURCE_COLUMNS].copy()
    normalized = normalized.to_crs("EPSG:4326")
    for column in ("cnig_national_code", "cnig_name", "ine_code"):
        normalized[column] = normalized[column].astype("string").str.strip()
        missing_values = normalized[column].isna() | normalized[column].eq("")
        if missing_values.any():
            raise ValueError(f"CNIG column {column!r} contains null or blank values.")

    invalid_ine_codes = ~normalized["ine_code"].str.fullmatch(r"\d{5}")
    invalid_cnig_codes = ~normalized["cnig_national_code"].str.fullmatch(r"\d{11}")
    if invalid_ine_codes.any():
        raise ValueError("CNIG ine_code values must contain exactly five digits.")
    if invalid_cnig_codes.any():
        raise ValueError("CNIG national codes must contain exactly eleven digits.")
    if not normalized["cnig_national_code"].str[-5:].eq(normalized["ine_code"]).all():
        raise ValueError("CNIG national codes must end with the corresponding ine_code.")

    normalized = normalized.loc[
        normalized["ine_code"].str[:2].isin(ANDALUSIA_PROVINCE_CODES)
    ].copy()
    if normalized.empty:
        raise ValueError("CNIG source contains no Andalusian municipalities.")

    invalid_geometries = (
        normalized.geometry.isna()
        | normalized.geometry.is_empty
        | ~normalized.geometry.is_valid
    )
    if invalid_geometries.any():
        codes = normalized.loc[invalid_geometries, "ine_code"].tolist()
        raise ValueError(f"CNIG contains null, empty, or invalid geometries: {codes[:10]}")
    if not normalized.geometry.geom_type.eq("MultiPolygon").all():
        raise ValueError("All CNIG municipality geometries must be MultiPolygon.")

    normalized = normalized.rename(
        columns={
            "ine_code": "municipality_code",
            "cnig_name": "municipality_name",
        }
    )
    normalized["_geometry_wkb"] = normalized.geometry.to_wkb()
    normalized = normalized.drop_duplicates(
        subset=[
            "municipality_code",
            "cnig_national_code",
            "municipality_name",
            "_geometry_wkb",
        ]
    ).drop(columns="_geometry_wkb")
    duplicate_codes = normalized["municipality_code"].duplicated(keep=False)
    if duplicate_codes.any():
        codes = normalized.loc[duplicate_codes, "municipality_code"].tolist()
        raise ValueError(f"Conflicting duplicate municipality codes found: {codes[:10]}")

    timestamp = pd.to_datetime(
        datetime.now(timezone.utc) if loaded_at_utc is None else loaded_at_utc,
        utc=True,
    )
    normalized["source"] = SOURCE_NAME
    normalized["loaded_at_utc"] = timestamp
    return normalized.loc[:, OUTPUT_COLUMNS].sort_values(
        "municipality_code",
        kind="stable",
    ).reset_index(drop=True)


def cnig_csv_to_geodataframe(raw_boundaries: pd.DataFrame) -> gpd.GeoDataFrame:
    """Convert the raw CNIG CSV columns and GeoJSON geometries to a GeoDataFrame."""
    required_columns = {"nationalCode", "name", "geometry"}
    missing_columns = sorted(required_columns.difference(raw_boundaries.columns))
    if missing_columns:
        raise ValueError(f"Missing required CNIG CSV columns: {missing_columns}")

    national_codes = raw_boundaries["nationalCode"].astype("string").str.strip()
    geometries = raw_boundaries["geometry"].map(
        lambda value: shape(json.loads(value)) if value.strip() else None
    )
    return gpd.GeoDataFrame(
        {
            "cnig_national_code": national_codes,
            "cnig_name": raw_boundaries["name"].astype("string").str.strip(),
            "ine_code": national_codes.str[-5:],
        },
        geometry=geometries,
        crs="EPSG:4326",
    )


def clean_municipality_boundaries_from_csv(
    source_csv_path: Path = MUNICIPALITY_BOUNDARIES_BRONZE_PATH,
    output_path: Path = MUNICIPALITY_BOUNDARIES_SILVER_PATH,
) -> Path:
    """Read CNIG's raw CSV and create a local Silver GeoParquet."""
    source_csv_path = Path(source_csv_path)
    output_path = Path(output_path)
    if source_csv_path.resolve() == output_path.resolve():
        raise ValueError("The raw CSV and processed Parquet paths must be different.")

    raw_boundaries = pd.read_csv(
        source_csv_path,
        dtype="string",
        keep_default_na=False,
    )
    source_boundaries = cnig_csv_to_geodataframe(raw_boundaries)
    silver_boundaries = clean_municipality_boundaries(source_boundaries)
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
