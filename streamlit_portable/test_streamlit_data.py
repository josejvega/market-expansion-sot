from __future__ import annotations

import io
import unittest
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, Polygon

from botocore.exceptions import NoCredentialsError
from streamlit_data import (
    add_municipality_coordinates,
    load_municipality_data,
    prepare_municipality_data,
)


def gold_data() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "municipality_code": ["04001", "04002"],
            "municipality_name": ["Abla", "Abrucena"],
            "province": ["Almería", "Almería"],
            "population_18_50": [35, 90],
            "population_growth_pct": [20.0, 10.0],
            "mean_net_income_per_person": [11000, 21000],
            "gyms_count": [2, 0],
            "other_sports_facilities_count": [1, 1],
            "gyms_per_10k_18_50": [571.43, 0.0],
        }
    )


def boundary_data() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "municipality_code": ["04001", "04002"],
            "geometry": [
                Polygon([(-2.0, 36.0), (-1.0, 36.0), (-1.0, 37.0), (-2.0, 37.0)]),
                Polygon([(-3.0, 37.0), (-2.0, 37.0), (-2.0, 38.0), (-3.0, 38.0)]),
            ],
        },
        crs="EPSG:4326",
    )


class MunicipalityDataTests(unittest.TestCase):
    def test_prepares_gold_without_optional_clusters(self) -> None:
        result, has_clusters = prepare_municipality_data(gold_data())

        self.assertFalse(has_clusters)
        self.assertEqual(result["municipality_code"].tolist(), ["04001", "04002"])
        self.assertEqual(result["gyms_count"].tolist(), [2, 0])

    def test_joins_complete_clusters_by_municipality_code(self) -> None:
        clusters = pd.DataFrame(
            {
                "municipality_code": ["04002", "04001"],
                "cluster": [1, 0],
            }
        )

        result, has_clusters = prepare_municipality_data(gold_data(), clusters)

        self.assertTrue(has_clusters)
        self.assertEqual(result["cluster"].tolist(), [0, 1])

    def test_rejects_duplicate_municipality_codes(self) -> None:
        duplicated = pd.concat([gold_data(), gold_data().iloc[[0]]])

        with self.assertRaisesRegex(ValueError, "debe ser único"):
            prepare_municipality_data(duplicated)

    def test_rejects_cluster_coverage_mismatch(self) -> None:
        clusters = pd.DataFrame(
            {"municipality_code": ["04001"], "cluster": [0]}
        )

        with self.assertRaisesRegex(ValueError, "coincidir exactamente"):
            prepare_municipality_data(gold_data(), clusters)

    def test_rejects_invalid_cluster_labels(self) -> None:
        clusters = pd.DataFrame(
            {
                "municipality_code": ["04001", "04002"],
                "cluster": [0, -1],
            }
        )

        with self.assertRaisesRegex(ValueError, "entero no negativo"):
            prepare_municipality_data(gold_data(), clusters)

    def test_rejects_zero_target_population(self) -> None:
        gold = gold_data()
        gold.loc[0, "population_18_50"] = 0

        with self.assertRaisesRegex(ValueError, "debe ser positiva"):
            prepare_municipality_data(gold)

    def test_adds_interior_coordinates_from_silver_polygons(self) -> None:
        gold, _ = prepare_municipality_data(gold_data())

        result = add_municipality_coordinates(gold, boundary_data())

        self.assertIn("lat", result.columns)
        self.assertIn("lon", result.columns)
        self.assertEqual(result.loc[0, "lon"], -1.5)
        self.assertEqual(result.loc[0, "lat"], 36.5)
        self.assertTrue(
            boundary_data().geometry.iloc[0].contains(
                Point(result.loc[0, "lon"], result.loc[0, "lat"])
            )
        )

    def test_allows_silver_boundaries_for_municipalities_absent_from_gold(self) -> None:
        gold, _ = prepare_municipality_data(gold_data())

        boundaries = pd.concat(
            [
                boundary_data(),
                gpd.GeoDataFrame(
                    {
                        "municipality_code": ["04999"],
                        "geometry": [
                            Polygon(
                                [
                                    (-4.0, 36.0),
                                    (-3.0, 36.0),
                                    (-3.0, 37.0),
                                    (-4.0, 37.0),
                                ]
                            )
                        ],
                    },
                    crs="EPSG:4326",
                ),
            ],
            ignore_index=True,
        )

        result = add_municipality_coordinates(gold, boundaries)

        self.assertEqual(result["municipality_code"].tolist(), ["04001", "04002"])
        self.assertEqual(result["lat"].tolist(), [36.5, 37.5])

    def test_rejects_gold_municipalities_without_silver_boundaries(self) -> None:
        gold, _ = prepare_municipality_data(gold_data())

        with self.assertRaisesRegex(
            ValueError,
            r"Faltan límites Silver para 1 municipios de Gold: \['04002'\]",
        ):
            add_municipality_coordinates(gold, boundary_data().iloc[:1])

    def test_loads_gold_parquet_and_optional_cluster_csv(self) -> None:
        with TemporaryDirectory() as directory:
            gold_path = Path(directory) / "gold.parquet"
            clusters_path = Path(directory) / "clusters.csv"
            boundaries_path = Path(directory) / "boundaries.parquet"
            gold_data().to_parquet(gold_path, index=False)
            boundary_data().to_parquet(boundaries_path, index=False)
            pd.DataFrame(
                {
                    "municipality_code": ["04001", "04002"],
                    "cluster": [0, 1],
                }
            ).to_csv(clusters_path, index=False)

            with patch(
                "streamlit_data.get_storage_settings",
                return_value=SimpleNamespace(bucket_name=None, region_name=None),
            ):
                result, has_clusters, source = load_municipality_data(
                    gold_path,
                    clusters_path,
                    boundaries_path,
                )

        self.assertTrue(has_clusters)
        self.assertEqual(result["cluster"].tolist(), [0, 1])
        self.assertEqual(source, "Local · gold.parquet")
        self.assertIn("lat", result.columns)

    def test_prefers_configured_s3_gold(self) -> None:
        gold_parquet = io.BytesIO()
        gold_data().to_parquet(gold_parquet, index=False)
        boundaries_parquet = io.BytesIO()
        boundary_data().to_parquet(boundaries_parquet, index=False)
        gold_parquet.seek(0)
        boundaries_parquet.seek(0)
        s3_client = unittest.mock.MagicMock()
        s3_client.get_object.side_effect = [
            {"Body": gold_parquet},
            {"Body": boundaries_parquet},
        ]

        with (
            patch(
                "streamlit_data.get_storage_settings",
                return_value=SimpleNamespace(
                    bucket_name="test-bucket",
                    region_name="eu-west-1",
                ),
            ),
            patch("streamlit_data.boto3.client", return_value=s3_client),
        ):
            result, has_clusters, source = load_municipality_data(
                Path("missing-gold.parquet")
            )

        self.assertFalse(has_clusters)
        self.assertEqual(result["municipality_code"].tolist(), ["04001", "04002"])
        self.assertEqual(source, "S3 · gold/missing-gold.parquet")
        self.assertEqual(result.loc[0, "lat"], 36.5)
        self.assertEqual(
            [call.kwargs["Key"] for call in s3_client.get_object.call_args_list],
            [
                "gold/missing-gold.parquet",
                "processed/silver/limites_municipales_andalucia.parquet",
            ],
        )

    def test_reports_missing_s3_credentials_without_local_fallback(self) -> None:
        s3_client = unittest.mock.MagicMock()
        s3_client.get_object.side_effect = NoCredentialsError()

        with (
            patch(
                "streamlit_data.get_storage_settings",
                return_value=SimpleNamespace(
                    bucket_name="test-bucket",
                    region_name=None,
                ),
            ),
            patch("streamlit_data.boto3.client", return_value=s3_client),
            self.assertRaisesRegex(RuntimeError, "credenciales AWS"),
        ):
            load_municipality_data(Path("missing-gold.parquet"))


if __name__ == "__main__":
    unittest.main()
