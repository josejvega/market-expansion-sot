from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from src.common.storage import StorageSettings
from src.procesado.tabla_oro import create_and_upload_gold_table, create_gold_table


def population_data() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "municipality_code": ["04001", "04001", "04001", "04002", "04002", "04003"],
            "municipality_name": ["Abla", "Abla", "Abla", "Abrucena", "Abrucena", "Adra"],
            "province_code": ["04"] * 6,
            "province": ["Almería"] * 6,
            "year": [2020, 2021, 2022, 2021, 2022, 2022],
            "population_total": [100, 110, 120, 200, 220, 50],
            "population_18_50": [30, 32, 35, 80, 90, 0],
        }
    )


def income_data() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "municipality_code": ["04001", "04001", "04002"],
            "year": [2021, 2022, 2023],
            "mean_net_income_per_person": [10000, 11000, 21000],
        }
    )


def gym_data() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "municipality_code": ["04001", "04001", "04001", "04002", None],
            "sport_centre_type": [
                "gym",
                "gym",
                "other_sport_facility",
                "other_sport_facility",
                "gym",
            ],
        }
    )


class GoldTableTests(unittest.TestCase):
    def test_builds_one_row_per_municipality_with_latest_values_and_growth(self) -> None:
        result = create_gold_table(population_data(), income_data(), gym_data())

        self.assertEqual(len(result), 3)
        self.assertEqual(result["municipality_code"].tolist(), ["04001", "04002", "04003"])
        self.assertEqual(
            result.columns.tolist(),
            [
                "municipality_code",
                "municipality_name",
                "province_code",
                "province",
                "population_year",
                "population_total",
                "population_18_50",
                "population_growth_start_year",
                "population_growth_pct",
                "income_year",
                "mean_net_income_per_person",
                "gyms_count",
                "other_sports_facilities_count",
                "gyms_per_10k_18_50",
            ],
        )
        first_municipality = result.loc[
            result["municipality_code"].eq("04001")
        ].iloc[0]
        self.assertEqual(first_municipality["population_year"], 2022)
        self.assertEqual(first_municipality["population_total"], 120)
        self.assertEqual(first_municipality["population_18_50"], 35)
        self.assertEqual(first_municipality["population_growth_start_year"], 2020)
        self.assertEqual(first_municipality["population_growth_pct"], 20.0)
        self.assertEqual(first_municipality["income_year"], 2022)
        self.assertEqual(first_municipality["mean_net_income_per_person"], 11000)
        self.assertEqual(first_municipality["gyms_count"], 2)
        self.assertEqual(first_municipality["other_sports_facilities_count"], 1)
        self.assertAlmostEqual(
            first_municipality["gyms_per_10k_18_50"],
            2 / 35 * 10_000,
        )

        second_municipality = result.loc[
            result["municipality_code"].eq("04002")
        ].iloc[0]
        self.assertEqual(second_municipality["population_growth_pct"], 10.0)
        self.assertEqual(second_municipality["income_year"], 2023)
        self.assertEqual(second_municipality["gyms_count"], 0)
        self.assertEqual(second_municipality["other_sports_facilities_count"], 1)
        self.assertEqual(
            second_municipality["gyms_per_10k_18_50"],
            0,
        )

        third_municipality = result.loc[
            result["municipality_code"].eq("04003")
        ].iloc[0]
        self.assertTrue(pd.isna(third_municipality["population_growth_pct"]))
        self.assertTrue(pd.isna(third_municipality["income_year"]))
        self.assertEqual(third_municipality["gyms_count"], 0)
        self.assertEqual(third_municipality["other_sports_facilities_count"], 0)
        self.assertTrue(
            pd.isna(
                third_municipality["gyms_per_10k_18_50"]
            )
        )

    def test_rejects_duplicate_municipality_year_rows(self) -> None:
        duplicated_population = pd.concat(
            [population_data(), population_data().iloc[[0]]],
            ignore_index=True,
        )

        with self.assertRaisesRegex(ValueError, "one row per municipality and year"):
            create_gold_table(
                duplicated_population,
                income_data(),
                gym_data(),
            )

    def test_persists_parquet_and_uploads_to_gold_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "gold.parquet"
            with (
                patch(
                    "src.procesado.tabla_oro.get_storage_settings",
                    return_value=StorageSettings(
                        True,
                        True,
                        "test-bucket",
                        "eu-test-1",
                    ),
                ),
                patch("src.procesado.tabla_oro.GOLD_TABLE_PATH", output_path),
                patch("src.procesado.tabla_oro.upload_files_to_s3") as upload,
            ):
                result = create_and_upload_gold_table(
                    population_data(),
                    income_data(),
                    gym_data(),
                )

            restored = pd.read_parquet(output_path)
            self.assertEqual(len(restored), len(result))
            self.assertEqual(
                restored["municipality_code"].tolist(),
                ["04001", "04002", "04003"],
            )
            upload.assert_called_once_with(
                [output_path],
                prefix="gold",
                bucket_name="test-bucket",
                region_name="eu-test-1",
            )

    def test_s3_only_uses_a_temporary_parquet_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "gold.parquet"
            uploaded_paths: list[Path] = []

            def assert_file_exists_during_upload(
                file_paths: list[Path],
                **_kwargs: object,
            ) -> None:
                uploaded_paths.extend(file_paths)
                self.assertTrue(file_paths[0].is_file())

            with (
                patch(
                    "src.procesado.tabla_oro.get_storage_settings",
                    return_value=StorageSettings(
                        False,
                        True,
                        "test-bucket",
                        "eu-test-1",
                    ),
                ),
                patch("src.procesado.tabla_oro.GOLD_TABLE_PATH", output_path),
                patch(
                    "src.procesado.tabla_oro.upload_files_to_s3",
                    side_effect=assert_file_exists_during_upload,
                ),
            ):
                create_and_upload_gold_table(
                    population_data(),
                    income_data(),
                    gym_data(),
                )

            self.assertEqual(len(uploaded_paths), 1)
            self.assertFalse(uploaded_paths[0].exists())
            self.assertFalse(output_path.exists())


if __name__ == "__main__":
    unittest.main()
