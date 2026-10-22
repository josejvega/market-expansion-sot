from __future__ import annotations

import io
import unittest
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from botocore.exceptions import NoCredentialsError
from streamlit_data import (
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

    def test_loads_gold_parquet_and_optional_cluster_csv(self) -> None:
        with TemporaryDirectory() as directory:
            gold_path = Path(directory) / "gold.parquet"
            clusters_path = Path(directory) / "clusters.csv"
            gold_data().to_parquet(gold_path, index=False)
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
                )

        self.assertTrue(has_clusters)
        self.assertEqual(result["cluster"].tolist(), [0, 1])
        self.assertEqual(source, str(gold_path))

    def test_prefers_configured_s3_gold(self) -> None:
        parquet = io.BytesIO()
        gold_data().to_parquet(parquet, index=False)
        parquet.seek(0)
        s3_client = unittest.mock.MagicMock()
        s3_client.get_object.return_value = {"Body": parquet}

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
        s3_client.get_object.assert_called_once_with(
            Bucket="test-bucket",
            Key="gold/missing-gold.parquet",
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
