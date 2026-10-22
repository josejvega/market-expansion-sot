from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from src.common.storage import StorageSettings
from src.procesado.tabla_municipios_dudosos import (
    create_and_upload_doubtful_municipalities_table,
    create_doubtful_municipalities_table,
)


def gold_table() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "municipality_code": [
                "04001",
                "04002",
                "04003",
                "04004",
                "04005",
                "04006",
                "04007",
            ],
            "municipality_name": ["Town"] * 7,
            "province": ["Almería"] * 7,
            "population_18_50": [
                10_000,
                20_000,
                10_000,
                30_000,
                1_000,
                10_000,
                1_000,
            ],
            "gyms_count": [2, 4, 0, 2, 0, 1, 1],
        }
    )


class DoubtfulMunicipalityTests(unittest.TestCase):
    def test_flags_low_counts_using_population_scaled_median_reference(self) -> None:
        review = create_doubtful_municipalities_table(gold_table())

        self.assertEqual(review["municipality_code"].tolist(), ["04003", "04004"])
        self.assertEqual(review["reference_gyms_per_10k_18_50"].tolist(), [1.5, 1.5])
        self.assertEqual(review["expected_gyms"].tolist(), [1.5, 4.5])
        self.assertAlmostEqual(
            review["observed_vs_expected_pct"].tolist()[1],
            200 / 4.5,
        )
        self.assertTrue(
            review["review_reason"]
            .str.contains("Posible infradetección")
            .all()
        )

    def test_does_not_flag_exactly_half_of_expected_count(self) -> None:
        gold = pd.DataFrame(
            {
                "municipality_code": ["04001", "04002", "04003"],
                "municipality_name": ["Town"] * 3,
                "province": ["Almería"] * 3,
                "population_18_50": [10_000, 20_000, 10_000],
                "gyms_count": [2, 4, 1],
            }
        )

        review = create_doubtful_municipalities_table(gold)

        self.assertTrue(review.empty)

    def test_uploads_review_table_to_processed_quality_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "doubtful.parquet"
            settings = StorageSettings(True, True, "test-bucket", "eu-test-1")
            with (
                patch(
                    "src.procesado.tabla_municipios_dudosos.get_storage_settings",
                    return_value=settings,
                ),
                patch(
                    "src.procesado.tabla_municipios_dudosos.DOUBTFUL_GYMS_TABLE_PATH",
                    output_path,
                ),
                patch(
                    "src.procesado.tabla_municipios_dudosos.upload_files_to_s3"
                ) as upload,
            ):
                report = create_and_upload_doubtful_municipalities_table(gold_table())

            self.assertEqual(len(report), 2)
            self.assertTrue(output_path.is_file())
            upload.assert_called_once_with(
                [output_path],
                prefix="processed/quality",
                bucket_name="test-bucket",
                region_name="eu-test-1",
            )


if __name__ == "__main__":
    unittest.main()
