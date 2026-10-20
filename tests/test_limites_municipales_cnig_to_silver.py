from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
import pandas as pd
from botocore.exceptions import ClientError
from shapely.geometry import MultiPolygon, box

from limites_municipales_cnig_to_silver import (
    OUTPUT_COLUMNS,
    clean_municipality_boundaries,
    parse_s3_uri,
    transform_cnig_municipality_boundaries,
)


LOADED_AT_UTC = "2026-10-20T07:00:00+00:00"


def boundaries_source() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "cnig_national_code": ["34010404001", "34011414001", "34010101001"],
            "cnig_name": [" Abla ", "Córdoba", "Municipio fuera de Andalucía"],
            "ine_code": ["04001", "14001", "01001"],
        },
        geometry=[
            MultiPolygon([box(-2.0, 36.0, -1.9, 36.1)]),
            MultiPolygon([box(-4.9, 37.8, -4.8, 37.9)]),
            MultiPolygon([box(-2.0, 42.5, -1.9, 42.6)]),
        ],
        crs="EPSG:4326",
    )


class FakeS3Client:
    def __init__(self, source_path: Path, object_exists: bool = False) -> None:
        self.source_path = source_path
        self.object_exists = object_exists
        self.uploaded_body: bytes | None = None
        self.upload_arguments: dict[str, object] = {}

    def download_file(self, bucket: str, key: str, filename: str) -> None:
        self.download_arguments = {"bucket": bucket, "key": key}
        shutil.copyfile(self.source_path, filename)

    def put_object(self, **arguments: object) -> dict[str, str]:
        self.upload_arguments = arguments
        if self.object_exists:
            raise ClientError(
                {
                    "Error": {"Code": "PreconditionFailed"},
                    "ResponseMetadata": {"HTTPStatusCode": 412},
                },
                "PutObject",
            )
        body = arguments["Body"]
        self.uploaded_body = body.read()  # type: ignore[union-attr]
        return {"ETag": '"test-etag"'}


class MunicipalityBoundariesTests(unittest.TestCase):
    def test_parse_s3_uri_returns_bucket_and_object_key(self) -> None:
        self.assertEqual(
            parse_s3_uri(
                "s3://sot-05-market-expansion/raw/data/limites_municipales_cnig.gpkg"
            ),
            (
                "sot-05-market-expansion",
                "raw/data/limites_municipales_cnig.gpkg",
            ),
        )

    def test_parse_s3_uri_rejects_bucket_only_and_non_s3_uri(self) -> None:
        with self.assertRaises(ValueError):
            parse_s3_uri("s3://bucket")
        with self.assertRaises(ValueError):
            parse_s3_uri("https://bucket/key")

    def test_clean_filters_and_normalizes_andalusian_municipalities(self) -> None:
        result = clean_municipality_boundaries(
            boundaries_source(),
            loaded_at_utc=LOADED_AT_UTC,
        )

        self.assertEqual(list(result.columns), OUTPUT_COLUMNS)
        self.assertEqual(result["municipality_code"].tolist(), ["04001", "14001"])
        self.assertEqual(result.iloc[0]["municipality_name"], "Abla")
        self.assertTrue(result["source"].eq("IGN/CNIG BDDAE").all())
        self.assertTrue(result["loaded_at_utc"].eq(pd.Timestamp(LOADED_AT_UTC)).all())
        self.assertEqual(result.crs.to_epsg(), 4326)
        self.assertTrue(result.geometry.geom_type.eq("MultiPolygon").all())

    def test_clean_deduplicates_exact_rows_and_rejects_conflicting_codes(self) -> None:
        one_row = boundaries_source().iloc[[0]]
        exact_duplicates = gpd.GeoDataFrame(
            pd.concat([one_row, one_row], ignore_index=True),
            geometry="geometry",
            crs="EPSG:4326",
        )
        cleaned = clean_municipality_boundaries(
            exact_duplicates,
            loaded_at_utc=LOADED_AT_UTC,
        )
        self.assertEqual(cleaned["municipality_code"].tolist(), ["04001"])

        conflicting = one_row.copy()
        conflicting["cnig_name"] = "Different name"
        conflicting = gpd.GeoDataFrame(
            pd.concat([one_row, conflicting], ignore_index=True),
            geometry="geometry",
            crs="EPSG:4326",
        )
        with self.assertRaisesRegex(ValueError, "Conflicting duplicate"):
            clean_municipality_boundaries(
                conflicting,
                loaded_at_utc=LOADED_AT_UTC,
            )

    def test_clean_rejects_null_values_and_inconsistent_codes(self) -> None:
        null_name = boundaries_source().iloc[[0]].copy()
        null_name.loc[null_name.index[0], "cnig_name"] = None
        with self.assertRaisesRegex(ValueError, "cnig_name"):
            clean_municipality_boundaries(
                null_name,
                loaded_at_utc=LOADED_AT_UTC,
            )

        mismatched_code = boundaries_source().iloc[[0]].copy()
        mismatched_code.loc[
            mismatched_code.index[0], "cnig_national_code"
        ] = "34010404002"
        with self.assertRaisesRegex(ValueError, "must end with"):
            clean_municipality_boundaries(
                mismatched_code,
                loaded_at_utc=LOADED_AT_UTC,
            )

    def test_transform_downloads_parquets_and_uploads_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            source_path = temporary_path / "source.gpkg"
            output_path = temporary_path / "result.parquet"
            boundaries_source().iloc[[0, 1]].to_file(
                source_path,
                layer="municipios",
                driver="GPKG",
            )
            fake_s3 = FakeS3Client(source_path)

            result_uri = transform_cnig_municipality_boundaries(
                "s3://raw-bucket/raw/municipios.gpkg",
                "s3://silver-bucket/processed/municipios.parquet",
                s3_client=fake_s3,  # type: ignore[arg-type]
            )

            self.assertEqual(
                fake_s3.download_arguments,
                {"bucket": "raw-bucket", "key": "raw/municipios.gpkg"},
            )
            self.assertEqual(result_uri, "s3://silver-bucket/processed/municipios.parquet")
            self.assertEqual(fake_s3.upload_arguments["IfNoneMatch"], "*")
            self.assertEqual(fake_s3.upload_arguments["ContentType"], "application/vnd.apache.parquet")
            self.assertIsNotNone(fake_s3.uploaded_body)
            output_path.write_bytes(fake_s3.uploaded_body or b"")
            restored = gpd.read_parquet(output_path)
            self.assertEqual(len(restored), 2)
            self.assertEqual(list(restored.columns), OUTPUT_COLUMNS)
            self.assertEqual(restored.crs.to_epsg(), 4326)

    def test_transform_fails_if_output_object_already_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source_path = Path(temporary_directory) / "source.gpkg"
            boundaries_source().iloc[[0]].to_file(
                source_path,
                layer="municipios",
                driver="GPKG",
            )
            fake_s3 = FakeS3Client(source_path, object_exists=True)

            with self.assertRaisesRegex(FileExistsError, "Refusing to overwrite"):
                transform_cnig_municipality_boundaries(
                    "s3://raw-bucket/raw/municipios.gpkg",
                    "s3://silver-bucket/processed/municipios.parquet",
                    s3_client=fake_s3,  # type: ignore[arg-type]
                )


if __name__ == "__main__":
    unittest.main()
