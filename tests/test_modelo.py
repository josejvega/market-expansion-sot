import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")

from src.modelo.modelo import (
    crear_modelo_kmeans,
    graficar_clusters_interactivo,
    graficar_metricas_kmeans,
    obtener_inercias,
    obtener_silhouette_scores,
    seleccionar_municipios_bajo_media_cluster,
    seleccionar_y_guardar_municipios_candidatos,
)
from src.modelo.prepara_variables_modelo import seleccionar_variables_modelo


class KMeansModelTests(unittest.TestCase):
    def setUp(self):
        self.X_escalado = np.array(
            [
                [-2.0, -1.8],
                [-1.8, -2.2],
                [-2.2, -2.0],
                [2.0, 1.8],
                [1.8, 2.2],
                [2.2, 2.0],
            ]
        )

    def test_inertias_accept_one_cluster_and_scaled_input(self):
        inertias = obtener_inercias([1, 2], self.X_escalado)

        self.assertEqual(len(inertias), 2)
        self.assertGreater(inertias[0], inertias[1])

    def test_silhouette_scores_accept_valid_cluster_counts(self):
        scores = obtener_silhouette_scores([2, 3], self.X_escalado)

        self.assertEqual(len(scores), 2)
        self.assertTrue(all(-1 <= score <= 1 for score in scores))

    def test_silhouette_rejects_one_cluster(self):
        with self.assertRaisesRegex(ValueError, "entre 2 y"):
            obtener_silhouette_scores([1], self.X_escalado)

    def test_silhouette_rejects_one_cluster_per_sample(self):
        with self.assertRaisesRegex(ValueError, "entre 2 y"):
            obtener_silhouette_scores([len(self.X_escalado)], self.X_escalado)

    def test_model_uses_requested_cluster_count(self):
        model = crear_modelo_kmeans(2, self.X_escalado)

        self.assertEqual(model.n_clusters, 2)
        self.assertEqual(np.unique(model.labels_).size, 2)

    def test_plot_shows_inertia_and_silhouette_for_separate_k_ranges(self):
        k_inercia = [1, 2, 3]
        k_silhouette = [2, 3, 4]

        with patch("src.modelo.modelo.plt.show"):
            figure, axes = graficar_metricas_kmeans(
                k_inercia,
                k_silhouette,
                self.X_escalado,
            )

        self.assertEqual(len(axes), 2)
        np.testing.assert_array_equal(axes[0].lines[0].get_xdata(), k_inercia)
        np.testing.assert_array_equal(
            axes[1].lines[0].get_xdata(),
            k_silhouette,
        )
        figure.clear()

    def test_plot_rejects_invalid_silhouette_k(self):
        with self.assertRaisesRegex(ValueError, "silhouette"):
            graficar_metricas_kmeans([1, 2], [1, 2], self.X_escalado)

    def test_interactive_plot_shows_all_clusters_with_compressed_scale(self):
        scaled = pd.DataFrame(
            [
                [-2.0, -1.8, -2.0],
                [-1.8, -2.2, -1.5],
                [2.0, 1.8, 2.0],
                [25.0, 2.2, 1.5],
            ],
            columns=[
                "population_18_50",
                "mean_net_income_per_person",
                "population_growth_pct",
            ],
        )
        municipalities = pd.DataFrame(
            {
                "municipality_name": ["Alfa", "Beta", "Gamma", "Delta"],
                "province": ["A", "A", "B", "B"],
            }
        )

        pairwise = graficar_clusters_interactivo(
            scaled,
            municipalities,
            [0, 0, 1, 2],
        )

        self.assertEqual(len(pairwise.data), 3)
        self.assertIn("Alfa", str(pairwise.data[0].hovertext))
        self.assertIn("province", pairwise.data[0].hovertemplate)
        self.assertIn("valor estandarizado", pairwise.data[0].hovertemplate)
        self.assertAlmostEqual(
            pairwise.data[-1].dimensions[0].values[0],
            np.arcsinh(25.0),
        )

    def test_interactive_cluster_plot_requires_three_variables(self):
        with self.assertRaisesRegex(ValueError, "exactamente tres"):
            graficar_clusters_interactivo(
                pd.DataFrame({"feature": [0, 1]}),
                pd.DataFrame({"municipality_name": ["Alfa", "Beta"]}),
                [0, 1],
            )

    def test_selects_municipalities_below_their_cluster_mean(self):
        municipalities = pd.DataFrame(
            {
                "municipality_code": ["00001", "00002", "00003", "00004"],
                "population_total": [100_000] * 4,
                "gyms_count": [2, 10, 5, 5],
                "other_sports_facilities_count": [0, 0, 0, 0],
            }
        )

        opportunities = seleccionar_municipios_bajo_media_cluster(
            municipalities,
            [0, 0, 1, 1],
        )

        self.assertEqual(opportunities["municipality_code"].tolist(), ["00001"])
        self.assertEqual(opportunities["cluster"].tolist(), [0])
        self.assertEqual(
            opportunities["media_tasa_ponderada_cluster"].tolist(),
            [6.0],
        )
        self.assertEqual(
            opportunities["tasa_ponderada_de_competidores"].tolist(),
            [2.0],
        )

    def test_opportunity_selection_requires_one_non_null_label_per_municipality(
        self,
    ):
        municipalities = pd.DataFrame(
            {
                "population_total": [100_000, 100_000],
                "gyms_count": [2, 10],
                "other_sports_facilities_count": [0, 0],
            }
        )

        with self.assertRaisesRegex(ValueError, "una etiqueta"):
            seleccionar_municipios_bajo_media_cluster(municipalities, [0])
        with self.assertRaisesRegex(ValueError, "no pueden contener"):
            seleccionar_municipios_bajo_media_cluster(municipalities, [0, None])

    def test_persists_candidates_and_all_cluster_assignments(self):
        municipalities = pd.DataFrame(
            {
                "municipality_code": ["00001", "00002", "00003", "00004"],
                "population_total": [100_000] * 4,
                "gyms_count": [2, 10, 5, 5],
                "other_sports_facilities_count": [0, 0, 0, 0],
            }
        )

        with TemporaryDirectory() as directory:
            results_dir = Path(directory) / "results"
            settings = SimpleNamespace(save_locally=True, save_s3=False)
            with (
                patch("src.modelo.modelo.RESULTS_DIR", results_dir),
                patch("src.modelo.modelo.get_storage_settings", return_value=settings),
            ):
                candidates = seleccionar_y_guardar_municipios_candidatos(
                    municipalities,
                    [0, 0, 1, 1],
                )

            assignments = pd.read_parquet(
                results_dir / "municipios_clusters.parquet"
            )
            saved_candidates = pd.read_parquet(
                results_dir / "municipios_candidatos.parquet"
            )

        self.assertEqual(candidates["municipality_code"].tolist(), ["00001"])
        self.assertEqual(saved_candidates["municipality_code"].tolist(), ["00001"])
        self.assertEqual(
            assignments.to_dict(orient="records"),
            [
                {"municipality_code": "00001", "cluster": 0},
                {"municipality_code": "00002", "cluster": 0},
                {"municipality_code": "00003", "cluster": 1},
                {"municipality_code": "00004", "cluster": 1},
            ],
        )

    def test_variable_selection_applies_log1p_to_population(self):
        municipalities = pd.DataFrame(
            {
                "population_18_50": [0, 99, 999],
                "mean_net_income_per_person": [10000, 20000, 30000],
                "population_growth_pct": [-1, 0, 1],
            },
            index=[3, 7, 9],
        )

        variables = seleccionar_variables_modelo(municipalities)

        self.assertEqual(
            variables.columns.tolist(),
            [
                "log1p_population_18_50",
                "mean_net_income_per_person",
                "population_growth_pct",
            ],
        )
        np.testing.assert_allclose(
            variables["log1p_population_18_50"],
            np.log1p(municipalities["population_18_50"]),
        )
        pd.testing.assert_series_equal(
            variables["mean_net_income_per_person"],
            municipalities["mean_net_income_per_person"],
        )
        pd.testing.assert_series_equal(
            variables["population_growth_pct"],
            municipalities["population_growth_pct"],
        )

    def test_variable_selection_rejects_negative_population(self):
        municipalities = pd.DataFrame(
            {
                "population_18_50": [-1],
                "mean_net_income_per_person": [10000],
                "population_growth_pct": [0],
            }
        )

        with self.assertRaisesRegex(ValueError, "valores negativos"):
            seleccionar_variables_modelo(municipalities)


if __name__ == "__main__":
    unittest.main()
