from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
import pandas as pd
from shapely.geometry import MultiPolygon, Point, box

from src.common.storage import StorageSettings
from src.procesado.cruzar_gimnasios_municipios import (
    assign_municipalities_to_gyms,
    cross_gym_municipality_tables,
)
from src.procesado.pipeline import cross_and_upload_gyms_municipalities


def municipality_boundaries() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "municipality_code": ["04001", "04002"],
            "municipality_name": ["Municipality A", "Municipality B"],
        },
        geometry=[
            MultiPolygon([box(0, 0, 1, 1)]),
            MultiPolygon([box(1, 0, 2, 1)]),
        ],
        crs="EPSG:4326",
    )


def gym_points() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "osm_type": ["node", "way", "node"],
            "osm_id": ["101", "202", "303"],
            "province_code": ["ES-AL", "ES-AL", "ES-AL"],
            "province": ["Almería", "Almería", "Almería"],
            "latitude": [0.5, 0.5, 2.0],
            "longitude": [0.5, 1.5, 3.0],
            "source": ["OpenStreetMap"] * 3,
            "downloaded_at_utc": pd.to_datetime(
                ["2026-10-20T15:31:28.373903+00:00"] * 3,
                utc=True,
            ),
            "tag_name": ["Gym A", "Sports hall", "Gym outside"],
            "tag_sport": ["fitness", None, "fitness"],
            "sport_centre_type": ["gym", "other_sport_facility", "gym"],
        },
        geometry=[
            Point(0.5, 0.5),
            Point(1.5, 0.5),
            Point(3.0, 2.0),
        ],
        crs="EPSG:4326",
    )


class CrossGymMunicipalityTests(unittest.TestCase):
    def test_assigns_municipality_without_dropping_unmatched_gyms(self) -> None:
        result = assign_municipalities_to_gyms(
            gym_points(),
            municipality_boundaries(),
        )

        self.assertEqual(len(result), 3)
        self.assertEqual(result["osm_id"].tolist(), ["101", "202", "303"])
        self.assertEqual(
            result["municipality_code"].iloc[:2].tolist(),
            ["04001", "04002"],
        )
        self.assertTrue(pd.isna(result["municipality_code"].iloc[2]))
        self.assertEqual(
            result["municipality_name"].iloc[:2].tolist(),
            ["Municipality A", "Municipality B"],
        )
        self.assertEqual(
            result.columns.tolist(),
            [
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
                "geometry",
                "municipality_code",
                "municipality_name",
            ],
        )
        self.assertEqual(
            result["tag_name"].tolist(),
            ["Gym A", "Sports hall", "Gym outside"],
        )
        self.assertEqual(
            result["sport_centre_type"].tolist(),
            ["gym", "other_sport_facility", "gym"],
        )
        self.assertTrue(result.geometry.geom_type.eq("Point").all())
        self.assertEqual(result.crs.to_epsg(), 4326)

    def test_reprojects_points_for_join_and_preserves_gym_crs(self) -> None:
        gyms = gym_points().to_crs("EPSG:3857")

        result = assign_municipalities_to_gyms(gyms, municipality_boundaries())

        self.assertEqual(result.crs.to_epsg(), 3857)
        self.assertEqual(
            result["municipality_code"].iloc[:2].tolist(),
            ["04001", "04002"],
        )

    def test_rejects_a_point_matching_multiple_municipalities(self) -> None:
        boundary_point = gym_points().iloc[[0]].copy()
        boundary_point.geometry = [Point(1.0, 0.5)]
        boundary_point["latitude"] = 0.5
        boundary_point["longitude"] = 1.0

        with self.assertRaisesRegex(ValueError, "multiple municipality boundaries"):
            assign_municipalities_to_gyms(
                boundary_point,
                municipality_boundaries(),
            )

    def test_rejects_coordinates_that_do_not_match_point_geometry(self) -> None:
        inconsistent_gym = gym_points().iloc[[0]].copy()
        inconsistent_gym["latitude"] = 0.75

        with self.assertRaisesRegex(ValueError, "do not match their Point geometries"):
            assign_municipalities_to_gyms(
                inconsistent_gym,
                municipality_boundaries(),
            )

    def test_reads_and_writes_silver_geoparquet(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            gyms_path = temporary_path / "gyms.parquet"
            municipalities_path = temporary_path / "municipalities.parquet"
            output_path = temporary_path / "joined.parquet"
            gym_points().to_parquet(gyms_path, index=False)
            municipality_boundaries().to_parquet(
                municipalities_path,
                index=False,
            )

            saved_path = cross_gym_municipality_tables(
                gyms_path,
                municipalities_path,
                output_path,
            )

            restored = gpd.read_parquet(saved_path)
            self.assertEqual(saved_path, output_path)
            self.assertEqual(len(restored), 3)
            self.assertEqual(
                restored["municipality_code"].iloc[:2].tolist(),
                ["04001", "04002"],
            )
            self.assertEqual(restored.crs.to_epsg(), 4326)

    def test_pipeline_persists_and_uploads_joined_parquet(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "gyms_joined.parquet"
            with (
                patch(
                    "src.procesado.pipeline.get_storage_settings",
                    return_value=StorageSettings(
                        True,
                        True,
                        "test-bucket",
                        "eu-test-1",
                    ),
                ),
                patch(
                    "src.procesado.pipeline.GYMS_WITH_MUNICIPALITY_SILVER_PATH",
                    output_path,
                ),
                patch("src.procesado.pipeline.upload_files_to_s3") as upload,
            ):
                result = cross_and_upload_gyms_municipalities(
                    gym_points(),
                    municipality_boundaries(),
                )

            restored = gpd.read_parquet(output_path)
            self.assertEqual(len(restored), len(result))
            self.assertEqual(restored.crs.to_epsg(), 4326)
            upload.assert_called_once_with(
                [output_path],
                prefix="processed/silver",
                bucket_name="test-bucket",
                region_name="eu-test-1",
            )


if __name__ == "__main__":
    unittest.main()
