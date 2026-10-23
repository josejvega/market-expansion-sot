import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")

from src.modelo.modelo import (
    CLUSTER_ASSIGNMENTS_FILENAME,
    MUNICIPALITY_CANDIDATES_FILENAME,
    crear_modelo_kmeans,
    guardar_asignaciones_clusters,
    guardar_municipios_candidatos,
    graficar_clusters_interactivo,
    graficar_metricas_kmeans,
    obtener_inercias,
    obtener_silhouette_scores,
    seleccionar_municipios_bajo_media_cluster,
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

    def test_persists_all_modelled_cluster_assignments(self):
        municipalities = pd.DataFrame(
            {
                "municipality_code": ["00001", "00002", "00003"],
                "cluster": [0, 1, 1],
            }
        )

        with TemporaryDirectory() as directory:
            output_path = Path(directory) / CLUSTER_ASSIGNMENTS_FILENAME
            settings = SimpleNamespace(
                save_locally=True,
                save_s3=True,
                bucket_name="test-bucket",
                region_name="test-region",
            )
            with (
                patch(
                    "src.modelo.modelo.CLUSTER_ASSIGNMENTS_PATH",
                    output_path,
                ),
                patch(
                    "src.modelo.modelo.get_storage_settings",
                    return_value=settings,
                ),
                patch("src.modelo.modelo.upload_files_to_s3") as upload,
            ):
                assignments = guardar_asignaciones_clusters(municipalities)

            saved = pd.read_parquet(output_path)

        pd.testing.assert_frame_equal(assignments, saved)
        self.assertEqual(assignments["municipality_code"].tolist(), [
            "00001", "00002", "00003",
        ])
        self.assertEqual(assignments["cluster"].tolist(), [0, 1, 1])
        upload.assert_called_once_with(
            [output_path],
            prefix="results",
            bucket_name="test-bucket",
            region_name="test-region",
        )

    def test_cluster_assignments_reject_invalid_codes_and_labels(self):
        invalid_codes = pd.DataFrame(
            {"municipality_code": ["abcde"], "cluster": [0]}
        )
        invalid_labels = pd.DataFrame(
            {"municipality_code": ["00001"], "cluster": [-1]}
        )

        with self.assertRaisesRegex(ValueError, "cinco dígitos"):
            guardar_asignaciones_clusters(invalid_codes)
        with self.assertRaisesRegex(ValueError, "entero no negativo"):
            guardar_asignaciones_clusters(invalid_labels)

    def test_persists_selected_candidates_for_downstream_consumers(self):
        candidates = pd.DataFrame(
            {
                "municipality_code": ["00001", "00003"],
                "cluster": [0, 1],
                "candidate_flag": [True, True],
            }
        )

        with TemporaryDirectory() as directory:
            output_path = Path(directory) / MUNICIPALITY_CANDIDATES_FILENAME
            settings = SimpleNamespace(
                save_locally=True,
                save_s3=False,
                bucket_name=None,
                region_name=None,
            )
            with (
                patch("src.modelo.modelo.RESULTS_DIR", Path(directory)),
                patch(
                    "src.modelo.modelo.get_storage_settings",
                    return_value=settings,
                ),
            ):
                saved_candidates = guardar_municipios_candidatos(candidates)

            saved = pd.read_parquet(output_path)

        pd.testing.assert_frame_equal(saved_candidates, saved)
        self.assertEqual(saved["municipality_code"].tolist(), ["00001", "00003"])
        self.assertEqual(saved["cluster"].tolist(), [0, 1])

    def test_persists_both_model_artifacts_to_s3_without_local_copies(self):
        municipalities = pd.DataFrame(
            {
                "municipality_code": ["00001", "00002"],
                "cluster": [0, 1],
            }
        )
        candidates = municipalities.iloc[[0]].copy()
        settings = SimpleNamespace(
            save_locally=False,
            save_s3=True,
            bucket_name="test-bucket",
            region_name="test-region",
        )
        uploaded_artifacts = []

        def inspect_upload(file_paths, **kwargs):
            for file_path in file_paths:
                path = Path(file_path)
                self.assertTrue(path.is_file())
                uploaded_artifacts.append(
                    (path.name, pd.read_parquet(path), kwargs)
                )

        with (
            patch(
                "src.modelo.modelo.get_storage_settings",
                return_value=settings,
            ),
            patch(
                "src.modelo.modelo.upload_files_to_s3",
                side_effect=inspect_upload,
            ) as upload,
        ):
            cluster_assignments = guardar_asignaciones_clusters(municipalities)
            saved_candidates = guardar_municipios_candidatos(candidates)

        self.assertEqual(upload.call_count, 2)
        self.assertEqual(
            [artifact[0] for artifact in uploaded_artifacts],
            ["clusters.parquet", MUNICIPALITY_CANDIDATES_FILENAME],
        )
        pd.testing.assert_frame_equal(
            uploaded_artifacts[0][1],
            cluster_assignments,
        )
        pd.testing.assert_frame_equal(
            uploaded_artifacts[1][1],
            saved_candidates,
        )
        self.assertTrue(
            all(artifact[2]["prefix"] == "results" for artifact in uploaded_artifacts)
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
