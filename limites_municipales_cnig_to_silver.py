"""Transform CNIG municipality boundaries from S3 into an Andalusia GeoParquet."""

from __future__ import annotations

import argparse
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

import boto3
import geopandas as gpd
import pandas as pd
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import ClientError

LOGGER = logging.getLogger(__name__)
SOURCE_S3_URI = "s3://sot-05-market-expansion/raw/data/limites_municipales_cnig.gpkg"
OUTPUT_S3_URI = (
    "s3://sot-05-market-expansion/processed/cnig/"
    "limites_municipales_andalucia.parquet"
)
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


def parse_s3_uri(uri: str) -> tuple[str, str]:
    """Return the bucket and object key from a complete S3 URI."""
    parsed = urlsplit(uri)
    key = unquote(parsed.path.lstrip("/"))
    if parsed.scheme != "s3" or not parsed.netloc or not key:
        raise ValueError(f"Expected an S3 object URI, got: {uri!r}")
    if parsed.query or parsed.fragment:
        raise ValueError("S3 object URIs must not contain a query or fragment.")
    return parsed.netloc, key


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


def transform_cnig_municipality_boundaries(
    source_s3_uri: str = SOURCE_S3_URI,
    output_s3_uri: str = OUTPUT_S3_URI,
    s3_client: BaseClient | None = None,
) -> str:
    """Read a CNIG GeoPackage from S3, transform it, and conditionally upload GeoParquet."""
    source_bucket, source_key = parse_s3_uri(source_s3_uri)
    output_bucket, output_key = parse_s3_uri(output_s3_uri)
    if (source_bucket, source_key) == (output_bucket, output_key):
        raise ValueError("Source and output S3 objects must be different.")

    client = s3_client or boto3.client(
        "s3",
        config=Config(
            connect_timeout=10,
            read_timeout=120,
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )
    with tempfile.TemporaryDirectory(prefix="cnig-silver-") as temporary_directory:
        temporary_path = Path(temporary_directory)
        source_path = temporary_path / "source.gpkg"
        parquet_path = temporary_path / "limites_municipales_andalucia.parquet"

        client.download_file(source_bucket, source_key, str(source_path))
        raw_boundaries = gpd.read_file(source_path, layer="municipios")
        silver_boundaries = clean_municipality_boundaries(raw_boundaries)
        silver_boundaries.to_parquet(
            parquet_path,
            index=False,
            compression="snappy",
        )

        try:
            with parquet_path.open("rb") as parquet_file:
                client.put_object(
                    Bucket=output_bucket,
                    Key=output_key,
                    Body=parquet_file,
                    ContentType="application/vnd.apache.parquet",
                    IfNoneMatch="*",
                )
        except ClientError as error:
            error_code = error.response.get("Error", {}).get("Code")
            status_code = error.response.get("ResponseMetadata", {}).get(
                "HTTPStatusCode"
            )
            if error_code == "PreconditionFailed" or status_code == 412:
                raise FileExistsError(
                    f"Refusing to overwrite existing S3 object: {output_s3_uri}"
                ) from error
            raise

    LOGGER.info(
        "Uploaded %s Andalusian municipality boundaries to %s.",
        len(silver_boundaries),
        output_s3_uri,
    )
    return output_s3_uri


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Transform the CNIG municipality GeoPackage into Silver GeoParquet."
    )
    parser.add_argument("--source-uri", default=SOURCE_S3_URI)
    parser.add_argument("--output-uri", default=OUTPUT_S3_URI)
    arguments = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    transform_cnig_municipality_boundaries(
        source_s3_uri=arguments.source_uri,
        output_s3_uri=arguments.output_uri,
    )


if __name__ == "__main__":
    main()
