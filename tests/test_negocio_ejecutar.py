import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd

from src.negocio import ejecutar
from src.negocio.supuestos import parametros
from src.negocio.valor_negocio import viabilidad


class ViabilidadNegocioTests(unittest.TestCase):
    def test_scales_cost_and_margin_using_capturable_members(self):
        parameters = parametros("central")
        capturable_members = pd.Series([1500.0, 4261.0])
        annual_revenue_per_member = parameters["ticket_mensual"] * 12
        uncapped_revenue = capturable_members * annual_revenue_per_member
        capped_members = capturable_members.clip(upper=parameters["capacidad"])
        evaluation = pd.DataFrame(
            {
                "socios_captables": capturable_members,
                "facturacion_sin_tope_capacidad": uncapped_revenue,
                "facturacion_anual": capped_members * annual_revenue_per_member,
            }
        )

        result = viabilidad(evaluation, parameters)

        expected_cost = parameters["coste_anual_club"] * (
            0.6
            + 0.4 * capturable_members / parameters["capacidad"]
        )
        expected_margin = uncapped_revenue - expected_cost
        pd.testing.assert_series_equal(
            result["coste_anual_escalado"],
            expected_cost.rename("coste_anual_escalado"),
        )
        pd.testing.assert_series_equal(
            result["margen_escalado_eur"],
            expected_margin.rename("margen_escalado_eur"),
        )
        self.assertEqual(result["viable"].tolist(), [False, True])
        self.assertTrue(
            (result["margen_eur"] == result["margen_escalado_eur"]).all()
        )

    def test_break_even_uses_the_scaled_cost_formula(self):
        parameters = parametros("central")
        evaluation = pd.DataFrame(
            {
                "socios_captables": [2000.0],
                "facturacion_sin_tope_capacidad": [
                    2000.0 * parameters["ticket_mensual"] * 12
                ],
                "facturacion_anual": [
                    2000.0 * parameters["ticket_mensual"] * 12
                ],
            }
        )

        result = viabilidad(evaluation, parameters)
        break_even_members = result["socios_break_even"].iloc[0]
        break_even_revenue = break_even_members * parameters["ticket_mensual"] * 12
        break_even_cost = parameters["coste_anual_club"] * (
            0.6 + 0.4 * break_even_members / parameters["capacidad"]
        )

        self.assertAlmostEqual(break_even_revenue, break_even_cost)


class CargarDatosNegocioTests(unittest.TestCase):
    def _gold(self):
        return pd.DataFrame(
            {
                "municipality_code": ["00001", "00002", "00003"],
                "municipality_name": ["Alfa", "Beta", "Gamma"],
                "population_18_50": [1000, 2000, 3000],
                "gyms_count": [1, 2, 3],
                "other_sports_facilities_count": [0, 1, 0],
            }
        )

    def _cluster_assignments(self, codes=("00001", "00003")):
        return pd.DataFrame(
            {
                "municipality_code": list(codes),
                "cluster": list(range(len(codes))),
            }
        )

    def test_cargar_returns_only_clustered_municipalities_without_fixed_count(self):
        with tempfile.TemporaryDirectory() as directory:
            gold_path = Path(directory) / "gold.parquet"
            clusters_path = Path(directory) / "clusters.parquet"
            self._gold().to_parquet(gold_path, index=False)
            self._cluster_assignments().to_parquet(clusters_path, index=False)
            settings = SimpleNamespace(
                save_locally=True,
                save_s3=False,
                bucket_name=None,
                region_name=None,
            )

            with patch.object(ejecutar, "ORO", gold_path), \
                    patch.object(ejecutar, "CLUSTER_ASSIGNMENTS_PATH", clusters_path), \
                    patch.object(
                        ejecutar,
                        "get_storage_settings",
                        return_value=settings,
                    ):
                datos = ejecutar.cargar()

        self.assertEqual(datos["municipality_code"].tolist(), ["00001", "00003"])
        self.assertEqual(datos["cluster"].tolist(), [0, 1])
        self.assertEqual(len(datos), 2)

    def test_cargar_rejects_cluster_codes_missing_from_gold(self):
        with tempfile.TemporaryDirectory() as directory:
            gold_path = Path(directory) / "gold.parquet"
            clusters_path = Path(directory) / "clusters.parquet"
            self._gold().to_parquet(gold_path, index=False)
            self._cluster_assignments(("00001", "00004")).to_parquet(
                clusters_path,
                index=False,
            )
            settings = SimpleNamespace(
                save_locally=True,
                save_s3=False,
                bucket_name=None,
                region_name=None,
            )

            with patch.object(ejecutar, "ORO", gold_path), \
                    patch.object(ejecutar, "CLUSTER_ASSIGNMENTS_PATH", clusters_path), \
                    patch.object(
                        ejecutar,
                        "get_storage_settings",
                        return_value=settings,
                    ):
                with self.assertRaisesRegex(ValueError, "no existen en Gold"):
                    ejecutar.cargar()

    def test_cargar_reads_gold_and_clusters_from_s3_when_not_saved_locally(self):
        gold_buffer = io.BytesIO()
        clusters_buffer = io.BytesIO()
        self._gold().to_parquet(gold_buffer, index=False)
        self._cluster_assignments().to_parquet(clusters_buffer, index=False)
        bodies = [
            io.BytesIO(gold_buffer.getvalue()),
            io.BytesIO(clusters_buffer.getvalue()),
        ]
        s3_client = MagicMock()
        s3_client.get_object.side_effect = [
            {"Body": bodies[0]},
            {"Body": bodies[1]},
        ]
        settings = SimpleNamespace(
            save_locally=False,
            save_s3=True,
            bucket_name="test-bucket",
            region_name="test-region",
        )

        with patch.object(ejecutar, "ORO", Path("gold.parquet")), \
                patch.object(
                    ejecutar,
                    "CLUSTER_ASSIGNMENTS_PATH",
                    Path("clusters.parquet"),
                ), \
                patch.object(
                    ejecutar,
                    "get_storage_settings",
                    return_value=settings,
                ), \
                patch.object(
                    ejecutar,
                    "s3_uri_for",
                    side_effect=lambda filename, prefix: (
                        f"s3://test-bucket/{prefix}/{filename}"
                    ),
                ), \
                patch.object(ejecutar.boto3, "client", return_value=s3_client):
            datos = ejecutar.cargar()

        self.assertEqual(datos["municipality_code"].tolist(), ["00001", "00003"])
        self.assertEqual(s3_client.get_object.call_count, 2)


class GuardarSalidasNegocioTests(unittest.TestCase):
    def _outputs(self):
        return {
            "municipios_evaluados_central.csv": pd.DataFrame(
                {
                    "municipality_code": ["00001"],
                    "facturacion_anual": [123.5],
                }
            )
        }

    def test_saves_business_outputs_locally(self):
        with tempfile.TemporaryDirectory() as directory:
            output_directory = Path(directory) / "outputs"
            settings = SimpleNamespace(
                save_locally=True,
                save_s3=False,
                bucket_name=None,
                region_name=None,
            )
            with patch.object(
                ejecutar,
                "get_storage_settings",
                return_value=settings,
            ), patch.object(ejecutar, "upload_files_to_s3") as upload:
                saved = ejecutar.guardar_salidas_negocio(
                    self._outputs(),
                    "# Informe de prueba\n",
                    directorio=output_directory,
                )

            self.assertEqual(
                pd.read_csv(
                    output_directory / "municipios_evaluados_central.csv",
                    dtype={"municipality_code": "string"},
                )["municipality_code"].tolist(),
                ["00001"],
            )
            self.assertEqual(
                (output_directory / "tablas_definitivas_negocio.md").read_text(
                    encoding="utf-8"
                ),
                "# Informe de prueba\n",
            )
            self.assertEqual(
                saved["tablas_definitivas_negocio.md"],
                output_directory / "tablas_definitivas_negocio.md",
            )
            upload.assert_not_called()

    def test_uploads_business_outputs_to_s3_without_local_copies(self):
        with tempfile.TemporaryDirectory() as directory:
            output_directory = Path(directory) / "outputs"
            uploaded_names = []
            settings = SimpleNamespace(
                save_locally=False,
                save_s3=True,
                bucket_name="test-bucket",
                region_name="test-region",
            )

            def inspect_upload(paths, **kwargs):
                self.assertEqual(kwargs["prefix"], "results/negocio")
                for path in paths:
                    self.assertTrue(Path(path).is_file())
                    uploaded_names.append(Path(path).name)
                return [
                    f"s3://test-bucket/results/negocio/{Path(path).name}"
                    for path in paths
                ]

            with patch.object(
                ejecutar,
                "get_storage_settings",
                return_value=settings,
            ), patch.object(
                ejecutar,
                "upload_files_to_s3",
                side_effect=inspect_upload,
            ) as upload:
                saved = ejecutar.guardar_salidas_negocio(
                    self._outputs(),
                    "# Informe de prueba\n",
                    directorio=output_directory,
                )

            self.assertFalse(output_directory.exists())
            self.assertEqual(
                uploaded_names,
                [
                    "municipios_evaluados_central.csv",
                    "tablas_definitivas_negocio.md",
                ],
            )
            self.assertEqual(
                saved["tablas_definitivas_negocio.md"],
                "s3://test-bucket/results/negocio/tablas_definitivas_negocio.md",
            )
            upload.assert_called_once()

    def test_saves_and_uploads_business_outputs_when_both_options_are_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            output_directory = Path(directory) / "outputs"
            settings = SimpleNamespace(
                save_locally=True,
                save_s3=True,
                bucket_name="test-bucket",
                region_name="test-region",
            )
            with patch.object(
                ejecutar,
                "get_storage_settings",
                return_value=settings,
            ), patch.object(ejecutar, "upload_files_to_s3") as upload:
                saved = ejecutar.guardar_salidas_negocio(
                    self._outputs(),
                    "# Informe de prueba\n",
                    directorio=output_directory,
                )

            self.assertTrue(
                (output_directory / "municipios_evaluados_central.csv").is_file()
            )
            self.assertTrue(
                (output_directory / "tablas_definitivas_negocio.md").is_file()
            )
            self.assertEqual(
                saved["tablas_definitivas_negocio.md"],
                output_directory / "tablas_definitivas_negocio.md",
            )
            upload.assert_called_once()

    def test_cleans_only_obsolete_s3_business_outputs(self):
        settings = SimpleNamespace(
            save_s3=True,
            bucket_name="test-bucket",
            region_name="test-region",
        )
        with patch.object(
            ejecutar,
            "get_storage_settings",
            return_value=settings,
        ), patch.object(ejecutar.boto3, "client") as client:
            deleted = ejecutar.limpiar_salidas_obsoletas_s3()

        client.assert_called_once_with("s3", region_name="test-region")
        self.assertEqual(
            [call.kwargs for call in client.return_value.delete_object.call_args_list],
            [
                {
                    "Bucket": "test-bucket",
                    "Key": "results/negocio/resumen_negocio.md",
                },
                {
                    "Bucket": "test-bucket",
                    "Key": "results/negocio/top_facturacion_central.csv",
                },
            ],
        )
        self.assertEqual(
            deleted,
            [
                "results/negocio/resumen_negocio.md",
                "results/negocio/top_facturacion_central.csv",
            ],
        )

    def test_requires_at_least_one_storage_destination(self):
        settings = SimpleNamespace(
            save_locally=False,
            save_s3=False,
            bucket_name=None,
            region_name=None,
        )
        with patch.object(
            ejecutar,
            "get_storage_settings",
            return_value=settings,
        ):
            with self.assertRaisesRegex(RuntimeError, "SAVE_LOCALLY o SAVE_S3"):
                ejecutar.guardar_salidas_negocio(
                    self._outputs(),
                    "# Informe de prueba\n",
                )


if __name__ == "__main__":
    unittest.main()
