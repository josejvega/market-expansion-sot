from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from src.negocio import ejecutar
from src.negocio.valor_negocio import (
    competidores_ponderados, evaluar, top5_diversificado_clusters,
    top5_facturacion, top5_modelo,
)


class BusinessIntegrationTests(unittest.TestCase):
    def test_business_report_has_readable_baseline_model_comparison(self):
        central = pd.DataFrame({
            "municipality_code": ["00001", "00002", "00003", "00004", "00005"],
            "municipality_name": ["A", "B", "C", "D", "E"],
            "population_18_50": [10000] * 5,
            "population_growth_pct": [1.0, -0.5, 3.0, 8.0, -2.0],
            "mean_net_income_per_person": [11000, 12000, 13000, 11500, 12500],
            "cluster": [0, 0, 1, 2, 3],
            "competidores_pond": [1] * 5,
            "comp_per_10k_18_50": [1] * 5,
            "media_cluster_comp_per_10k": [2] * 5,
            "socios_captables": [2600] * 5,
            "facturacion_sin_tope_capacidad": [700000] * 5,
            "ratio_capacidad": [1] * 5,
            "colchon_demanda_pct": [0.1] * 5,
            "facturacion_anual": [600000] * 5,
            "margen_eur": [44000] * 5,
            "perdidas_eur": [0] * 5,
            "demanda_por_comp": [100] * 5,
            "viable": [True] * 5,
            "candidate_flag": [True] * 5,
            "socios_break_even": [2071.23] * 5,
            "umbral_facturacion": [556000] * 5,
            "aviso_calidad": [""] * 5,
        })
        diversificada = central.assign(
            posicion=range(1, 6), motivo_seleccion="mejor_candidato_viable_del_cluster"
        )
        diversificada.attrs["cluster_sin_candidato_viable"] = []
        selecciones = {
            "baseline": central,
            "maxima_facturacion": central,
            "modelo_a": central,
            "diversificada": diversificada,
        }
        frecuencias = pd.DataFrame({
            "municipality_code": central.municipality_code,
            "municipality_name": central.municipality_name,
            "apariciones": [4] * 5,
            "posicion_media": [1.0] * 5,
            "fact_min": [500000] * 5,
            "fact_max": [600000] * 5,
            "robustez": ["4 de 10"] * 5,
            "aviso_calidad": [""] * 5,
        })
        report = ejecutar.crear_reporte(
            selecciones, central, frecuencias, {"capacidad": 2600}
        )
        comparison = ejecutar.crear_comparacion_estrategias(selecciones)

        self.assertEqual(
            sum(line.startswith("| ---") for line in report.splitlines()), 7
        )
        self.assertIn("Máxima facturación sin clusters", report)
        self.assertIn("Modelo A oficial", report)
        self.assertIn("Alternativa diversificada por clusters", report)
        self.assertIn("Estado provisional y perfil de clusters", report)
        self.assertIn("Población 18-50 mediana", report)
        self.assertIn("Candidatos viables", report)
        self.assertIn("Lectura de perfiles:", report)
        for cluster in range(4):
            self.assertIn(f"- Cluster {cluster}:", report)
        self.assertIn("no son probabilidades", report)
        self.assertIn("potencial teórico sin límite de capacidad", report.lower())
        self.assertEqual(len(comparison), 4)
        self.assertIn("cluster_sin_candidato_viable", comparison.columns)

    def test_t5_cleanup_preserves_unmanaged_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_t5 = root / "baseline_solo_gimnasios.csv"
            unrelated = root / "evaluacion_clusters.csv"
            old_t5.write_text("old", encoding="utf-8")
            unrelated.write_text("keep", encoding="utf-8")

            removed = ejecutar.limpiar_salidas_t5(root)

            self.assertIn(old_t5.name, removed)
            self.assertFalse(old_t5.exists())
            self.assertEqual(unrelated.read_text(encoding="utf-8"), "keep")

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
        self.assertEqual(
            central.aviso_calidad.tolist(),
            ["", "Sin gimnasios en OSM: validar con una segunda fuente"],
        )
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

    def test_economic_selections_use_municipality_code_as_final_tiebreaker(self):
        rows = pd.DataFrame({
            "municipality_code": ["00005", "00003", "00001", "00006", "00002", "00004"],
            "facturacion_anual": [100] * 6,
            "facturacion_sin_tope_capacidad": [100] * 6,
            "demanda_por_comp": [10] * 6,
            "population_18_50": [1000] * 6,
            "candidate_flag": [True] * 6,
            "viable": [True] * 6,
        })

        actual = top5_facturacion(rows).municipality_code.tolist()

        self.assertEqual(actual, ["00001", "00002", "00003", "00004", "00005"])

    def test_diversified_selection_uses_cluster_winners_then_one_repeat(self):
        rows = pd.DataFrame({
            "municipality_code": ["00001", "00002", "00003", "00004", "00005", "00006"],
            "municipality_name": ["A", "A2", "B", "C", "D", "D2"],
            "cluster": [0, 0, 1, 2, 3, 3],
            "facturacion_anual": [100, 99, 95, 80, 70, 69],
            "facturacion_sin_tope_capacidad": [100, 99, 95, 80, 70, 69],
            "demanda_por_comp": [10, 9, 8, 7, 6, 5],
            "population_18_50": [1000] * 6,
            "candidate_flag": [True] * 6,
            "viable": [True] * 6,
        })

        actual = top5_diversificado_clusters(rows)

        self.assertEqual(actual.municipality_code.tolist(), [
            "00001", "00003", "00004", "00005", "00002",
        ])
        self.assertEqual(actual.cluster.value_counts().max(), 2)
        self.assertEqual(actual.cluster.value_counts().eq(2).sum(), 1)
        self.assertEqual(actual.posicion.tolist(), [1, 2, 3, 4, 5])
        self.assertEqual(actual.motivo_seleccion.tolist(), [
            "mejor_candidato_viable_del_cluster",
            "mejor_candidato_viable_del_cluster",
            "mejor_candidato_viable_del_cluster",
            "mejor_candidato_viable_del_cluster",
            "unica_repeticion_mejor_restante",
        ])

    def test_diversified_selection_repeats_only_one_cluster_without_relaxing_filters(self):
        rows = pd.DataFrame({
            "municipality_code": [
                "00001", "00002", "00003", "00004", "00005", "00006", "00007",
            ],
            "cluster": [0, 0, 1, 1, 2, 3, 3],
            "facturacion_anual": [100, 90, 80, 70, 999, 60, 50],
            "facturacion_sin_tope_capacidad": [100, 90, 80, 70, 999, 60, 50],
            "demanda_por_comp": [10, 9, 8, 7, 100, 6, 5],
            "population_18_50": [1000] * 7,
            "candidate_flag": [True, True, True, True, False, True, True],
            "viable": [True] * 7,
        })

        actual = top5_diversificado_clusters(rows)

        self.assertEqual(actual.attrs["cluster_sin_candidato_viable"], [2])
        self.assertEqual(actual.municipality_code.tolist(), [
            "00001", "00003", "00006", "00002",
        ])
        self.assertNotIn("00005", actual.municipality_code.tolist())
        self.assertEqual(
            actual.motivo_seleccion.tolist()[3],
            "unica_repeticion_mejor_restante",
        )
        self.assertEqual(actual.cluster.value_counts().max(), 2)
        self.assertEqual(actual.cluster.value_counts().eq(2).sum(), 1)
        self.assertEqual(actual.municipality_code.nunique(), len(actual))

    def test_diversified_selection_returns_three_when_only_two_clusters_are_viable(self):
        rows = pd.DataFrame({
            "municipality_code": ["00001", "00002", "00003", "00004", "00005"],
            "cluster": [0, 1, 2, 2, 3],
            "facturacion_anual": [100, 90, 80, 70, 60],
            "facturacion_sin_tope_capacidad": [100, 90, 80, 70, 60],
            "demanda_por_comp": [10, 9, 8, 7, 6],
            "population_18_50": [1000] * 5,
            "candidate_flag": [True] * 5,
            "viable": [False, True, True, True, False],
        })

        actual = top5_diversificado_clusters(rows)

        self.assertEqual(actual.municipality_code.tolist(), ["00002", "00003", "00004"])
        self.assertEqual(actual.cluster.value_counts().to_dict(), {2: 2, 1: 1})
        self.assertEqual(actual.attrs["cluster_sin_candidato_viable"], [0, 3])
        self.assertTrue((actual.candidate_flag & actual.viable).all())


if __name__ == "__main__":
    unittest.main()
