"""Assign each OSM gym point to its CNIG municipality."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd

LOGGER = logging.getLogger(__name__)
GYM_REQUIRED_COLUMNS = [
    "osm_type",
    "osm_id",
    "province_code",
    "province",
    "latitude",
    "longitude",
    "source",
    "downloaded_at_utc",
    "tag_name",
    "tag_sport",
    "sport_centre_type",
]
MUNICIPALITY_REQUIRED_COLUMNS = ["municipality_code", "municipality_name"]
GYM_COORDINATE_TOLERANCE = 1e-6


def assign_municipalities_to_gyms(
    gyms: gpd.GeoDataFrame,
    municipalities: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """Add the containing municipality code and name to each gym point."""
    if not isinstance(gyms, gpd.GeoDataFrame):
        raise TypeError("Gyms must be a GeoDataFrame with point geometries.")
    if not isinstance(municipalities, gpd.GeoDataFrame):
        raise TypeError("Municipalities must be a GeoDataFrame with polygon geometries.")

    missing_gym_columns = sorted(set(GYM_REQUIRED_COLUMNS).difference(gyms.columns))
    if missing_gym_columns:
        raise ValueError(f"Missing required gym columns: {missing_gym_columns}")
    missing_municipality_columns = sorted(
        set(MUNICIPALITY_REQUIRED_COLUMNS).difference(municipalities.columns)
    )
    if missing_municipality_columns:
        raise ValueError(
            "Missing required municipality columns: "
            f"{missing_municipality_columns}"
        )
    if "geometry" not in gyms.columns or gyms.geometry.name != "geometry":
        raise ValueError("The gym table must have an active 'geometry' column.")
    if (
        "geometry" not in municipalities.columns
        or municipalities.geometry.name != "geometry"
    ):
        raise ValueError("The municipality table must have an active 'geometry' column.")
    if gyms.crs is None:
        raise ValueError("Gym points must have a declared CRS.")
    if municipalities.crs is None:
        raise ValueError("Municipality boundaries must have a declared CRS.")
    if {"municipality_code", "municipality_name"}.intersection(gyms.columns):
        raise ValueError(
            "The gym table already contains municipality_code or municipality_name."
        )
    if gyms.empty:
        raise ValueError("The gym table contains no records.")
    if municipalities.empty:
        raise ValueError("The municipality table contains no boundaries.")

    gym_geometries = gyms.geometry
    invalid_gym_geometries = (
        gym_geometries.isna()
        | gym_geometries.is_empty
        | ~gym_geometries.is_valid
        | ~gym_geometries.geom_type.eq("Point")
    )
    if invalid_gym_geometries.any():
        rows = invalid_gym_geometries[invalid_gym_geometries].index.tolist()
        raise ValueError(f"Gym geometries must be valid Points; invalid rows: {rows[:10]}")

    latitude = pd.to_numeric(gyms["latitude"], errors="coerce").reset_index(drop=True)
    longitude = pd.to_numeric(gyms["longitude"], errors="coerce").reset_index(drop=True)
    invalid_coordinates = (
        latitude.isna()
        | longitude.isna()
        | ~latitude.between(-90, 90)
        | ~longitude.between(-180, 180)
    )
    if invalid_coordinates.any():
        rows = invalid_coordinates[invalid_coordinates].index.tolist()
        raise ValueError(
            "Gym latitude/longitude values must be numeric and within valid ranges; "
            f"invalid rows: {rows[:10]}"
        )

    points_in_wgs84 = gyms.loc[:, ["geometry"]].copy().reset_index(drop=True)
    points_in_wgs84 = points_in_wgs84.set_crs(gyms.crs, allow_override=True).to_crs(
        "EPSG:4326"
    )
    geometry_longitude = pd.Series([point.x for point in points_in_wgs84.geometry])
    geometry_latitude = pd.Series([point.y for point in points_in_wgs84.geometry])
    mismatched_coordinates = (
        (geometry_latitude - latitude).abs().gt(GYM_COORDINATE_TOLERANCE)
        | (geometry_longitude - longitude).abs().gt(GYM_COORDINATE_TOLERANCE)
    )
    if mismatched_coordinates.any():
        rows = mismatched_coordinates[mismatched_coordinates].index.tolist()
        raise ValueError(
            "Gym latitude/longitude values do not match their Point geometries "
            f"within {GYM_COORDINATE_TOLERANCE} degrees; rows: {rows[:10]}"
        )

    municipality_geometries = municipalities.geometry
    valid_municipality_types = municipality_geometries.geom_type.isin(
        ["Polygon", "MultiPolygon"]
    )
    invalid_municipality_geometries = (
        municipality_geometries.isna()
        | municipality_geometries.is_empty
        | ~municipality_geometries.is_valid
        | ~valid_municipality_types
    )
    if invalid_municipality_geometries.any():
        rows = invalid_municipality_geometries[
            invalid_municipality_geometries
        ].index.tolist()
        raise ValueError(
            "Municipality geometries must be valid polygons; "
            f"invalid rows: {rows[:10]}"
        )

    municipality_codes = municipalities["municipality_code"].astype("string").str.strip()
    invalid_codes = (
        municipality_codes.isna()
        | municipality_codes.eq("")
        | ~municipality_codes.str.fullmatch(r"\d{5}").fillna(False)
    )
    if invalid_codes.any():
        rows = invalid_codes[invalid_codes].index.tolist()
        raise ValueError(f"Municipality codes must contain five digits; rows: {rows[:10]}")
    if municipality_codes.duplicated().any():
        duplicate_codes = municipality_codes.loc[
            municipality_codes.duplicated(keep=False)
        ].tolist()
        raise ValueError(
            "Municipality codes must be unique; duplicates: "
            f"{duplicate_codes[:10]}"
        )

    municipality_names = municipalities["municipality_name"].astype("string").str.strip()
    missing_names = municipality_names.isna() | municipality_names.eq("")
    if missing_names.any():
        rows = missing_names[missing_names].index.tolist()
        raise ValueError(f"Municipality names cannot be blank; rows: {rows[:10]}")

    gym_rows = gyms.copy().reset_index(drop=True)
    gym_rows["_gym_row_id"] = range(len(gym_rows))
    boundaries = municipalities.loc[
        :,
        ["municipality_code", "municipality_name", "geometry"],
    ].copy().reset_index(drop=True)
    boundaries["municipality_code"] = municipality_codes.reset_index(drop=True)
    boundaries["municipality_name"] = municipality_names.reset_index(drop=True)

    points_in_boundary_crs = gym_rows.to_crs(municipalities.crs)
    joined = gpd.sjoin(
        points_in_boundary_crs,
        boundaries,
        how="left",
        predicate="intersects",
    )
    match_counts = joined.loc[joined["municipality_code"].notna()].groupby(
        "_gym_row_id"
    ).size()
    ambiguous_ids = match_counts.loc[match_counts > 1].index.tolist()
    if ambiguous_ids:
        raise ValueError(
            "Some gym points intersect multiple municipality boundaries; "
            f"row ids: {ambiguous_ids[:10]}"
        )

    unmatched_count = int(joined["municipality_code"].isna().sum())
    if unmatched_count:
        LOGGER.warning(
            "%s gym points did not intersect any municipality boundary.",
            unmatched_count,
        )

    joined = joined.sort_values("_gym_row_id", kind="stable")
    if "index_right" in joined.columns:
        joined = joined.drop(columns="index_right")
    joined = joined.drop(columns="_gym_row_id").reset_index(drop=True)
    joined["municipality_code"] = joined["municipality_code"].astype("string")
    joined["municipality_name"] = joined["municipality_name"].astype("string")
    output_columns = [
        *gyms.columns.tolist(),
        "municipality_code",
        "municipality_name",
    ]
    return gpd.GeoDataFrame(
        joined,
        geometry="geometry",
        crs=municipalities.crs,
    ).to_crs(gyms.crs).loc[:, output_columns]


def cross_gym_municipality_tables(
    gyms_parquet_path: Path,
    municipalities_parquet_path: Path,
    output_parquet_path: Path,
) -> Path:
    """Read the two Silver GeoParquets, assign municipalities, and save the result."""
    gyms_parquet_path = Path(gyms_parquet_path)
    municipalities_parquet_path = Path(municipalities_parquet_path)
    output_parquet_path = Path(output_parquet_path)
    if not gyms_parquet_path.is_file():
        raise FileNotFoundError(f"OSM Silver GeoParquet not found: {gyms_parquet_path}")
    if not municipalities_parquet_path.is_file():
        raise FileNotFoundError(
            f"CNIG Silver GeoParquet not found: {municipalities_parquet_path}"
        )
    if output_parquet_path.resolve() in {
        gyms_parquet_path.resolve(),
        municipalities_parquet_path.resolve(),
    }:
        raise ValueError("The joined output path must differ from both input paths.")

    gyms = gpd.read_parquet(gyms_parquet_path)
    municipalities = gpd.read_parquet(municipalities_parquet_path)
    joined = assign_municipalities_to_gyms(gyms, municipalities)

    output_parquet_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_parquet_path.with_suffix(
        output_parquet_path.suffix + ".tmp"
    )
    try:
        joined.to_parquet(
            temporary_path,
            index=False,
            compression="snappy",
        )
        temporary_path.replace(output_parquet_path)
    finally:
        temporary_path.unlink(missing_ok=True)

    assigned_count = int(joined["municipality_code"].notna().sum())
    LOGGER.info(
        "Saved %s gyms with %s municipality assignments to %s.",
        len(joined),
        assigned_count,
        output_parquet_path,
    )
    return output_parquet_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Assign CNIG municipalities to OSM gym points."
    )
    parser.add_argument("--gyms-parquet", type=Path, required=True)
    parser.add_argument("--municipalities-parquet", type=Path, required=True)
    parser.add_argument("--output-parquet", type=Path, required=True)
    arguments = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    cross_gym_municipality_tables(
        gyms_parquet_path=arguments.gyms_parquet,
        municipalities_parquet_path=arguments.municipalities_parquet,
        output_parquet_path=arguments.output_parquet,
    )


if __name__ == "__main__":
    main()
