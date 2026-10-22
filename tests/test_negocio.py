from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from src.negocio import ejecutar
from src.negocio.valor_negocio import competidores_ponderados, evaluar, top5_modelo


class BusinessIntegrationTests(unittest.TestCase):
    def test_gold_competition_matches_agreed_weights_and_legacy_schema(self):
        gold = pd.DataFrame({
            "population_18_50": [10000, 20000],
            "gyms_count": [2, 0],
            "other_sports_facilities_count": [10, 5],
            "cluster": [0, 0],
        })
        legacy = gold.drop(columns=["gyms_count", "other_sports_facilities_count"]).assign(
            comp_fitness_centre=[2, 0],
            comp_sports_centre=[7, 3],
            comp_fitness_station=[3, 2],
        )
        for scenario in ["central", "solo_gimnasios", "todo_igual"]:
            actual = evaluar(gold, pesos=scenario, con_candidatos=True)
            expected = evaluar(legacy, pesos=scenario, con_candidatos=True)
            for column in ["competidores_pond", "comp_per_10k_18_50",
                           "candidate_flag", "facturacion_anual", "viable"]:
                pd.testing.assert_series_equal(actual[column], expected[column])
        central = competidores_ponderados(gold)
        self.assertEqual(central.competidores_pond.tolist(), [3.0, 0.5])
        with self.assertRaisesRegex(ValueError, "pesos distintos"):
            competidores_ponderados(gold, {
                "fitness_centre": 1, "sports_centre": 0.1, "fitness_station": 0,
            })
        with self.assertRaisesRegex(ValueError, "finitos"):
            competidores_ponderados(gold.assign(gyms_count=np.nan))

    def test_loading_links_exact_gold_universe_and_prefers_csv(self):
        codes = pd.Series([f"{4000 + i:05d}" for i in range(785)], dtype="string")
        gold = pd.DataFrame({
            "municipality_code": codes, "municipality_name": "Municipality",
            "population_18_50": 10000, "gyms_count": 2,
            "other_sports_facilities_count": 10,
        })
        clusters = pd.DataFrame({"municipality_code": codes, "cluster": np.arange(785) % 4})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gold_path = root / "gold.parquet"
            csv_path = root / "clusters.csv"
            parquet_path = root / "clusters.parquet"
            gold.to_parquet(gold_path, index=False)
            clusters.to_csv(csv_path, index=False)
            clusters.assign(cluster=99).to_parquet(parquet_path, index=False)
            with (patch.object(ejecutar, "ORO", gold_path),
                  patch.object(ejecutar, "CLUSTERS", [csv_path, parquet_path])):
                loaded = ejecutar.cargar()
                self.assertEqual(len(loaded), 785)
                self.assertEqual(loaded.municipality_code.iloc[0], "04000")
                self.assertEqual(loaded.cluster.nunique(), 4)
                clusters.assign(municipality_code=codes.where(codes.ne("04000"), "99999")).to_csv(csv_path, index=False)
                with self.assertRaisesRegex(ValueError, "exactamente"):
                    ejecutar.cargar()
                clusters.iloc[:-1].to_csv(csv_path, index=False)
                with self.assertRaisesRegex(ValueError, "785"):
                    ejecutar.cargar()
                clusters.assign(cluster=np.nan).to_csv(csv_path, index=False)
                with self.assertRaisesRegex(ValueError, "entero"):
                    ejecutar.cargar()
                csv_path.unlink()
                parquet_path.unlink()
                with self.assertRaises(FileNotFoundError):
                    ejecutar.cargar()
                gold_path.unlink()
                with self.assertRaises(FileNotFoundError):
                    ejecutar.cargar()

    def test_model_selection_uses_cluster_mean_and_viability(self):
        df = pd.DataFrame({
            "municipality_code": ["04001", "04002", "04003"],
            "population_18_50": [100000, 100000, 100],
            "gyms_count": [0, 100, 0],
            "other_sports_facilities_count": [0, 0, 0],
            "cluster": [0, 0, 0],
        })
        evaluated = evaluar(df, con_candidatos=True)
        self.assertEqual(evaluated.candidate_flag.tolist(), [True, False, True])
        self.assertEqual(top5_modelo(evaluated).municipality_code.tolist(), ["04001"])


if __name__ == "__main__":
    unittest.main()
