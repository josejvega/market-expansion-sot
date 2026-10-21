from __future__ import annotations

import unittest

import pandas as pd

from src.modelo.baseline import select_top_municipalities


class BaselineTests(unittest.TestCase):
    def test_selects_top_five_from_latest_year_with_deterministic_ties(self) -> None:
        population = pd.DataFrame(
            {
                "municipality_code": ["00006", "00001", "00002", "00003", "00004", "00005"],
                "municipality_name": ["F", "A", "B", "C", "D", "E"],
                "year": [2024, 2025, 2025, 2025, 2025, 2025],
                "population_18_50": [999, 100, 500, 400, 300, 200],
            }
        )

        result = select_top_municipalities(population)

        self.assertEqual(result["municipality_code"].tolist(), ["00002", "00003", "00004", "00005", "00001"])
        self.assertEqual(result["baseline_rank"].tolist(), [1, 2, 3, 4, 5])
        self.assertTrue(result["year"].eq(2025).all())

    def test_rejects_duplicate_municipality_in_selected_year(self) -> None:
        population = pd.DataFrame(
            {
                "municipality_code": ["00001", "00001"],
                "municipality_name": ["A", "A"],
                "year": [2025, 2025],
                "population_18_50": [100, 101],
            }
        )

        with self.assertRaisesRegex(ValueError, "one row per municipality"):
            select_top_municipalities(population)
