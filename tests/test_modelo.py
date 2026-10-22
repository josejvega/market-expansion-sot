from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from src.modelo.modelo import (
    MIN_CLUSTER_SIZE,
    save_clusters,
    train_model,
)


def gold_data() -> pd.DataFrame:
    rng = np.random.default_rng(123)
    group = np.arange(785) % 3
    return pd.DataFrame(
        {
            "municipality_code": pd.Series(
                [f"{4000 + i:05d}" for i in range(785)], dtype="string"
            ),
            "population_18_50": np.exp(
                5 + group * 2 + rng.normal(0, 0.2, 785)
            ).astype(int),
            "population_growth_pct": group * 4 + rng.normal(0, 0.5, 785),
            "mean_net_income_per_person": 10000 + group * 2000 + rng.normal(0, 100, 785),
            "gyms_count": rng.integers(0, 20, 785),
            "other_sports_facilities_count": rng.integers(0, 20, 785),
        }
    )


class ModelTests(unittest.TestCase):
    def test_model_contract_selection_and_reproducibility(self) -> None:
        gold = gold_data()
        gold.loc[:1, "mean_net_income_per_person"] = np.nan
        original = gold.copy(deep=True)
        with self.assertLogs("src.modelo.modelo", level="WARNING"):
            result = train_model(gold)
        pd.testing.assert_frame_equal(gold, original)
        self.assertEqual(result.clusters.shape, (785, 2))
        self.assertEqual(result.clusters.columns.tolist(), ["municipality_code", "cluster"])
        self.assertEqual(result.imputed_municipalities, ["04000", "04001"])
        self.assertEqual(
            result.income_median, gold["mean_net_income_per_person"].median()
        )
        self.assertTrue(result.clusters.municipality_code.is_unique)
        self.assertTrue(result.clusters.municipality_code.str.fullmatch(r"\d{5}").all())
        self.assertGreaterEqual(result.clusters.cluster.value_counts().min(), MIN_CLUSTER_SIZE)
        eligible = result.evaluation.loc[result.evaluation.eligible]
        selected = result.evaluation.loc[result.evaluation.selected].iloc[0]
        self.assertEqual(selected.silhouette, eligible.silhouette.max())
        self.assertEqual(result.evaluation.k.tolist(), [2, 3, 4, 5, 6])
        self.assertEqual(result.scaler.feature_names_in_.tolist(), [
            "log1p_population_18_50",
            "population_growth_pct",
            "mean_net_income_per_person",
        ])
        changed_competition = gold.sample(frac=1, random_state=7).copy()
        changed_competition["gyms_count"] = 99999
        changed_competition["other_sports_facilities_count"] = 0
        repeated = train_model(changed_competition)
        pd.testing.assert_frame_equal(result.clusters, repeated.clusters)

    def test_rejects_invalid_universe_codes_and_features(self) -> None:
        gold = gold_data()
        cases = [
            (gold.iloc[:-1], "785"),
            (gold.assign(municipality_code="04000"), "unique"),
            (gold.assign(municipality_code="4000"), "five-digit"),
            (gold.drop(columns="population_growth_pct"), "Missing model feature"),
            (gold.assign(population_18_50=0), "positive"),
            (gold.assign(population_growth_pct=np.nan), "missing values"),
            (gold.assign(population_growth_pct=np.inf), "infinite"),
            (gold.assign(mean_net_income_per_person=-1), "negative"),
            (gold.assign(mean_net_income_per_person=np.nan), "observed income"),
        ]
        for source, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    train_model(source)

    def test_fails_if_no_cluster_solution_satisfies_minimum_size(self) -> None:
        with patch("src.modelo.modelo.MIN_CLUSTER_SIZE", 785):
            with self.assertRaisesRegex(ValueError, "No k in 2..6"):
                train_model(gold_data())

    def test_csv_roundtrip_keeps_codes_and_only_two_columns(self) -> None:
        clusters = gold_data().loc[:, ["municipality_code"]].assign(
            cluster=np.arange(785) % 3
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "resultados" / "clusters.csv"
            save_clusters(clusters, output)
            restored = pd.read_csv(output, dtype={"municipality_code": "string"})
            pd.testing.assert_frame_equal(restored, clusters)
            self.assertIn("04000,0", output.read_text(encoding="utf-8"))
            self.assertFalse(output.with_suffix(".csv.tmp").exists())

    def test_invalid_output_does_not_replace_previous_file(self) -> None:
        clusters = gold_data().loc[:, ["municipality_code"]].assign(cluster=0)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "clusters.csv"
            output.write_text("previous", encoding="utf-8")
            for invalid in [
                clusters.assign(cluster=0.5),
                clusters.assign(cluster=-1),
                clusters.assign(cluster=np.inf),
                clusters.assign(extra=1),
                clusters.iloc[:-1],
            ]:
                with self.assertRaises(ValueError):
                    save_clusters(invalid, output)
                self.assertEqual(output.read_text(encoding="utf-8"), "previous")


if __name__ == "__main__":
    unittest.main()
