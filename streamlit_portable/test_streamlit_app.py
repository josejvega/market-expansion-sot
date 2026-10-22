from __future__ import annotations

import unittest

import pandas as pd

from streamlit_app import build_study, render_study
from streamlit_data import prepare_municipality_data


class OriginalExportDashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        gold = pd.DataFrame(
            {
                "municipality_code": [f"0400{index}" for index in range(1, 7)],
                "municipality_name": [
                    "Municipio 1",
                    "Municipio 2",
                    "Municipio 3",
                    "Municipio 4",
                    "Municipio 5",
                    "Municipio 6",
                ],
                "province": ["Almería"] * 6,
                "population_18_50": [1000, 1200, 1400, 1600, 1800, 2000],
                "population_growth_pct": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
                "mean_net_income_per_person": [
                    18000,
                    19000,
                    20000,
                    21000,
                    22000,
                    23000,
                ],
                "gyms_per_10k_18_50": [10.0, 9.0, 8.0, 7.0, 6.0, 5.0],
                "gyms_count": [2, 3, 4, 5, 6, 7],
                "other_sports_facilities_count": [1, 1, 1, 1, 1, 1],
                "population_year": [2024] * 6,
            }
        )
        self.municipalities, _ = prepare_municipality_data(gold)

    def test_builds_export_schema_from_gold_without_fabricated_coordinates(self) -> None:
        study = build_study(
            self.municipalities,
            has_clusters=False,
            gold_source="S3 · gold/tabla_oro_municipios_andalucia.parquet",
        )

        self.assertEqual(study["source_type"], "gold")
        self.assertEqual(len(study["baseline"]), 5)
        self.assertIsNone(study["municipalities"][0]["lat"])
        self.assertIsNone(study["municipalities"][0]["lon"])
        self.assertIsNone(study["municipalities"][0]["score"])
        self.assertFalse(study["clusters_available"])
        self.assertEqual(study["municipalities"][0]["tourism_beds"], None)

    def test_renders_original_export_layout_and_gold_adapter(self) -> None:
        study = build_study(
            self.municipalities,
            has_clusters=False,
            gold_source="S3 · gold/tabla_oro_municipios_andalucia.parquet",
        )

        html = render_study(study)

        self.assertIn("tab-situation", html)
        self.assertIn("tab-intelligence", html)
        self.assertIn("tab-decision", html)
        self.assertIn("renderGoldDashboard", html)
        self.assertIn("source_type", html)
        self.assertNotIn("__DATA__", html)
        self.assertNotIn("__MARKET__", html)


if __name__ == "__main__":
    unittest.main()
