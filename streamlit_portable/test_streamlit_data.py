from __future__ import annotations

import io
import unittest
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, Polygon

from botocore.exceptions import ClientError, NoCredentialsError
from streamlit_data import (
    AUDIT_SAMPLE_S3_KEY,
    BUSINESS_OUTPUTS,
    add_municipality_coordinates,
    load_audit_sample,
    load_business_outputs,
    load_municipality_data,
    prepare_competitor_records,
    prepare_model_candidates,
    prepare_municipality_data,
)


def gold_data() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "municipality_code": ["04001", "04002"],
            "municipality_name": ["Abla", "Abrucena"],
            "province": ["Almería", "Almería"],
            "population_year": [2024, 2024],
            "population_18_50": [35, 90],
            "population_growth_pct": [20.0, 10.0],
            "mean_net_income_per_person": [11000, 21000],
            "gyms_count": [2, 0],
            "other_sports_facilities_count": [1, 1],
            "gyms_per_10k_18_50": [571.43, 0.0],
        }
    )


def boundary_data() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "municipality_code": ["04001", "04002"],
            "geometry": [
                Polygon([(-2.0, 36.0), (-1.0, 36.0), (-1.0, 37.0), (-2.0, 37.0)]),
                Polygon([(-3.0, 37.0), (-2.0, 37.0), (-2.0, 38.0), (-3.0, 38.0)]),
            ],
        },
        crs="EPSG:4326",
    )


def candidate_data() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "municipality_code": ["04001"],
            "cluster": [2],
            "tasa_ponderada_de_competidores": [571.43],
        }
    )


def competitor_data() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "osm_type": ["node"],
            "osm_id": ["12345"],
            "latitude": [36.5],
            "longitude": [-1.5],
            "tag_name": [pd.NA],
            "municipality_code": ["04001"],
            "geometry": [Point(-1.5, 36.5)],
        },
        crs="EPSG:4326",
    )


class MunicipalityDataTests(unittest.TestCase):
    def test_prepares_gold_without_optional_clusters(self) -> None:
        result, has_clusters = prepare_municipality_data(gold_data())

        self.assertFalse(has_clusters)
        self.assertEqual(result["municipality_code"].tolist(), ["04001", "04002"])
        self.assertEqual(result["gyms_count"].tolist(), [2, 0])

    def test_joins_complete_clusters_by_municipality_code(self) -> None:
        clusters = pd.DataFrame(
            {
                "municipality_code": ["04002", "04001"],
                "cluster": [1, 0],
            }
        )

        result, has_clusters = prepare_municipality_data(gold_data(), clusters)

        self.assertTrue(has_clusters)
        self.assertEqual(result["cluster"].tolist(), [0, 1])

    def test_rejects_duplicate_municipality_codes(self) -> None:
        duplicated = pd.concat([gold_data(), gold_data().iloc[[0]]])

        with self.assertRaisesRegex(ValueError, "debe ser único"):
            prepare_municipality_data(duplicated)

    def test_rejects_cluster_coverage_mismatch(self) -> None:
        clusters = pd.DataFrame(
            {"municipality_code": ["04001"], "cluster": [0]}
        )

        with self.assertRaisesRegex(ValueError, "coincidir exactamente"):
            prepare_municipality_data(gold_data(), clusters)

    def test_rejects_invalid_cluster_labels(self) -> None:
        clusters = pd.DataFrame(
            {
                "municipality_code": ["04001", "04002"],
                "cluster": [0, -1],
            }
        )

        with self.assertRaisesRegex(ValueError, "entero no negativo"):
            prepare_municipality_data(gold_data(), clusters)

    def test_joins_candidate_only_model_output_to_gold(self) -> None:
        municipalities, _ = prepare_municipality_data(gold_data())

        result, has_candidates = prepare_model_candidates(
            municipalities,
            candidate_data(),
        )

        self.assertTrue(has_candidates)
        self.assertEqual(result["candidate_flag"].tolist(), [True, False])
        self.assertEqual(result["cluster"].tolist(), [2, pd.NA])

    def test_rejects_candidate_codes_missing_from_gold(self) -> None:
        municipalities, _ = prepare_municipality_data(gold_data())
        candidates = candidate_data().assign(municipality_code=["04999"])

        with self.assertRaisesRegex(ValueError, "ausentes de Gold"):
            prepare_model_candidates(municipalities, candidates)

    def test_formats_geolocated_osm_silver_records_for_dashboard(self) -> None:
        records = prepare_competitor_records(competitor_data())

        self.assertEqual(
            records,
            [
                {
                    "name": "Instalación OSM node/12345",
                    "lat": 36.5,
                    "lon": -1.5,
                    "url": "https://www.openstreetmap.org/node/12345",
                }
            ],
        )

    def test_rejects_zero_target_population(self) -> None:
        gold = gold_data()
        gold.loc[0, "population_18_50"] = 0

        with self.assertRaisesRegex(ValueError, "debe ser positiva"):
            prepare_municipality_data(gold)

    def test_adds_interior_coordinates_from_silver_polygons(self) -> None:
        gold, _ = prepare_municipality_data(gold_data())

        result = add_municipality_coordinates(gold, boundary_data())

        self.assertIn("lat", result.columns)
        self.assertIn("lon", result.columns)
        self.assertEqual(result.loc[0, "lon"], -1.5)
        self.assertEqual(result.loc[0, "lat"], 36.5)
        self.assertTrue(
            boundary_data().geometry.iloc[0].contains(
                Point(result.loc[0, "lon"], result.loc[0, "lat"])
            )
        )

    def test_allows_silver_boundaries_for_municipalities_absent_from_gold(self) -> None:
        gold, _ = prepare_municipality_data(gold_data())

        boundaries = pd.concat(
            [
                boundary_data(),
                gpd.GeoDataFrame(
                    {
                        "municipality_code": ["04999"],
                        "geometry": [
                            Polygon(
                                [
                                    (-4.0, 36.0),
                                    (-3.0, 36.0),
                                    (-3.0, 37.0),
                                    (-4.0, 37.0),
                                ]
                            )
                        ],
                    },
                    crs="EPSG:4326",
                ),
            ],
            ignore_index=True,
        )

        result = add_municipality_coordinates(gold, boundaries)

        self.assertEqual(result["municipality_code"].tolist(), ["04001", "04002"])
        self.assertEqual(result["lat"].tolist(), [36.5, 37.5])

    def test_rejects_gold_municipalities_without_silver_boundaries(self) -> None:
        gold, _ = prepare_municipality_data(gold_data())

        with self.assertRaisesRegex(
            ValueError,
            r"Faltan límites Silver para 1 municipios de Gold: \['04002'\]",
        ):
            add_municipality_coordinates(gold, boundary_data().iloc[:1])

    def test_loads_local_model_candidates_and_competitor_silver(self) -> None:
        with TemporaryDirectory() as directory:
            gold_path = Path(directory) / "gold.parquet"
            candidates_path = Path(directory) / "municipios_candidatos.parquet"
            boundaries_path = Path(directory) / "boundaries.parquet"
            competitors_path = Path(directory) / "gyms_with_municipality.parquet"
            gold_data().to_parquet(gold_path, index=False)
            boundary_data().to_parquet(boundaries_path, index=False)
            candidate_data().to_parquet(candidates_path, index=False)
            competitor_data().to_parquet(competitors_path, index=False)

            with patch(
                "streamlit_data.get_storage_settings",
                return_value=SimpleNamespace(bucket_name=None, region_name=None),
            ):
                result, has_candidates, source, competitors = load_municipality_data(
                    gold_path,
                    boundaries_path=boundaries_path,
                    candidates_path=candidates_path,
                    competitor_points_path=competitors_path,
                )

        self.assertTrue(has_candidates)
        self.assertEqual(result["candidate_flag"].tolist(), [True, False])
        self.assertEqual(result.loc[0, "cluster"], 2)
        self.assertTrue(pd.isna(result.loc[1, "cluster"]))
        self.assertEqual(source, "Local · gold.parquet")
        self.assertIn("lat", result.columns)
        self.assertEqual(len(competitors), 1)


class BusinessOutputsTests(unittest.TestCase):
    def _table(self, code: str, name: str) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "municipality_code": [code],
                "municipality_name": [name],
                "facturacion_anual": [1234.5],
                "demanda_por_comp": [98.2],
            }
        )

    def _comparison(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "estrategia": ["Baseline", "Modelo A oficial"],
                "centros_seleccionados": [5, 5],
                "centros_viables": [3, 5],
                "facturacion_operativa_total_eur": [2500000.0, 3400000.0],
                "margen_operativo_total_eur": [-100000.0, 600000.0],
                "perdidas_operativas_totales_eur": [300000.0, 0.0],
                "demanda_media_por_competidor": [900.0, 2100.0],
            }
        )

    def _robustness(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "municipality_code": ["04001"],
                "municipality_name": ["Abla"],
                "apariciones": [67],
                "posicion_media": [2.1],
                "robustez": ["67 de 108"],
                "combinaciones_totales": [108],
                "fact_min": [581908.0],
            }
        )

    def test_loads_business_selection_and_baseline_from_local_exports(self) -> None:
        with TemporaryDirectory() as directory:
            output_dir = Path(directory)
            self._table("04001", "Abla").to_csv(
                output_dir / BUSINESS_OUTPUTS["selection"],
                index=False,
                encoding="utf-8-sig",
            )
            baseline = pd.concat(
                [
                    self._table(f"0400{index}", f"Municipio {index}")
                    for index in range(1, 6)
                ],
                ignore_index=True,
            )
            baseline.to_csv(
                output_dir / BUSINESS_OUTPUTS["baseline"],
                index=False,
                encoding="utf-8-sig",
            )
            self._comparison().to_csv(
                output_dir / BUSINESS_OUTPUTS["comparison"],
                index=False,
                encoding="utf-8-sig",
            )
            self._robustness().to_csv(
                output_dir / BUSINESS_OUTPUTS["robustness"],
                index=False,
                encoding="utf-8-sig",
            )

            with patch(
                "streamlit_data.get_storage_settings",
                return_value=SimpleNamespace(bucket_name=None, region_name=None),
            ):
                tables, source = load_business_outputs(output_dir)

        self.assertEqual(source, f"Local · {output_dir}")
        self.assertEqual(tables["selection"]["municipality_code"].tolist(), ["04001"])
        self.assertEqual(
            tables["baseline"]["municipality_code"].tolist(),
            [f"0400{index}" for index in range(1, 6)],
        )
        self.assertEqual(
            tables["selection"].loc[0, "facturacion_anual"],
            1234.5,
        )
        self.assertEqual(
            tables["comparison"]["estrategia"].tolist(),
            ["Baseline", "Modelo"],
        )
        self.assertEqual(tables["robustness"].loc[0, "apariciones"], 67)

    def test_loads_business_selection_and_baseline_from_s3(self) -> None:
        selection = io.BytesIO(
            self._table("04001", "Abla").to_csv(index=False).encode("utf-8")
        )
        baseline = pd.concat(
            [
                self._table(f"0400{index}", f"Municipio {index}")
                for index in range(1, 6)
            ],
            ignore_index=True,
        )
        baseline_buffer = io.BytesIO(baseline.to_csv(index=False).encode("utf-8"))
        comparison_buffer = io.BytesIO(
            self._comparison().to_csv(index=False).encode("utf-8")
        )
        robustness_buffer = io.BytesIO(
            self._robustness().to_csv(index=False).encode("utf-8")
        )
        s3_client = unittest.mock.MagicMock()
        s3_client.get_object.side_effect = [
            {"Body": selection},
            {"Body": baseline_buffer},
            {"Body": comparison_buffer},
            {"Body": robustness_buffer},
        ]

        with (
            patch(
                "streamlit_data.get_storage_settings",
                return_value=SimpleNamespace(
                    bucket_name="test-bucket",
                    region_name="eu-west-1",
                ),
            ),
            patch("streamlit_data.boto3.client", return_value=s3_client),
        ):
            tables, source = load_business_outputs()

        self.assertEqual(source, "S3 · results/negocio/")
        self.assertEqual(tables["selection"]["municipality_code"].tolist(), ["04001"])
        self.assertEqual(
            [call.kwargs["Key"] for call in s3_client.get_object.call_args_list],
            [
                "results/negocio/seleccion_modelo_central.csv",
                "results/negocio/baseline_central.csv",
                "results/negocio/comparacion_estrategias_central.csv",
                "results/negocio/sensibilidad_frecuencias.csv",
            ],
        )

    def test_accepts_legacy_comparison_csv_column_names(self) -> None:
        with TemporaryDirectory() as directory:
            output_dir = Path(directory)
            self._table("04001", "Abla").to_csv(
                output_dir / BUSINESS_OUTPUTS["selection"],
                index=False,
                encoding="utf-8-sig",
            )
            pd.concat(
                [
                    self._table(f"0400{index}", f"Municipio {index}")
                    for index in range(1, 6)
                ],
                ignore_index=True,
            ).to_csv(
                output_dir / BUSINESS_OUTPUTS["baseline"],
                index=False,
                encoding="utf-8-sig",
            )
            comparison = self._comparison().rename(
                columns={
                    "facturacion_operativa_total_eur":
                        "facturacion_anual_total_con_tope_eur",
                    "margen_operativo_total_eur":
                        "margen_operativo_anual_total_eur",
                }
            )
            comparison.to_csv(
                output_dir / BUSINESS_OUTPUTS["comparison"],
                index=False,
                encoding="utf-8-sig",
            )
            self._robustness().to_csv(
                output_dir / BUSINESS_OUTPUTS["robustness"],
                index=False,
                encoding="utf-8-sig",
            )

            with patch(
                "streamlit_data.get_storage_settings",
                return_value=SimpleNamespace(bucket_name=None, region_name=None),
            ):
                tables, _ = load_business_outputs(output_dir)

        self.assertIn(
            "facturacion_operativa_total_eur",
            tables["comparison"].columns,
        )
        self.assertIn("margen_operativo_total_eur", tables["comparison"].columns)

    def test_normalizes_business_strategy_label_to_modelo(self) -> None:
        with TemporaryDirectory() as directory:
            output_dir = Path(directory)
            self._table("04001", "Abla").to_csv(
                output_dir / BUSINESS_OUTPUTS["selection"],
                index=False,
                encoding="utf-8-sig",
            )
            pd.concat(
                [
                    self._table(f"0400{index}", f"Municipio {index}")
                    for index in range(1, 6)
                ],
                ignore_index=True,
            ).to_csv(
                output_dir / BUSINESS_OUTPUTS["baseline"],
                index=False,
                encoding="utf-8-sig",
            )
            comparison = self._comparison().replace(
                {"estrategia": {"Modelo A oficial": "Modelo"}}
            )
            comparison.to_csv(
                output_dir / BUSINESS_OUTPUTS["comparison"],
                index=False,
                encoding="utf-8-sig",
            )
            self._robustness().to_csv(
                output_dir / BUSINESS_OUTPUTS["robustness"],
                index=False,
                encoding="utf-8-sig",
            )

            with patch(
                "streamlit_data.get_storage_settings",
                return_value=SimpleNamespace(bucket_name=None, region_name=None),
            ):
                tables, _ = load_business_outputs(output_dir)

        self.assertIn("Modelo", tables["comparison"]["estrategia"].tolist())

    def test_requires_s3_bucket_for_manual_competitor_audit(self) -> None:
        with patch(
            "streamlit_data.get_storage_settings",
            return_value=SimpleNamespace(bucket_name=None, region_name=None),
        ):
            with self.assertRaisesRegex(RuntimeError, "no se permite leerla desde local"):
                load_audit_sample()

    def test_loads_manual_competitor_audit_from_s3(self) -> None:
        audit_csv = (
            "name,municipality_name,status,finding,evidence_url,checked_date\n"
            "Club,Sevilla,reference_found,Referencia localizada,"
            "https://example.com,2026-10-26\n"
        )
        s3_client = unittest.mock.MagicMock()
        s3_client.get_object.return_value = {
            "Body": io.BytesIO(audit_csv.encode("utf-8"))
        }

        with (
            patch(
                "streamlit_data.get_storage_settings",
                return_value=SimpleNamespace(
                    bucket_name="test-bucket",
                    region_name="eu-west-1",
                ),
            ),
            patch("streamlit_data.boto3.client", return_value=s3_client),
        ):
            audit, source = load_audit_sample()

        self.assertEqual(audit[0]["name"], "Club")
        self.assertEqual(source, f"S3 · {AUDIT_SAMPLE_S3_KEY}")
        s3_client.get_object.assert_called_once_with(
            Bucket="test-bucket",
            Key=AUDIT_SAMPLE_S3_KEY,
        )

    def test_loads_without_optional_local_model_artifacts(self) -> None:
        with TemporaryDirectory() as directory:
            gold_path = Path(directory) / "gold.parquet"
            boundaries_path = Path(directory) / "boundaries.parquet"
            gold_data().to_parquet(gold_path, index=False)
            boundary_data().to_parquet(boundaries_path, index=False)

            with patch(
                "streamlit_data.get_storage_settings",
                return_value=SimpleNamespace(bucket_name=None, region_name=None),
            ):
                result, has_candidates, _, competitors = load_municipality_data(
                    gold_path,
                    boundaries_path=boundaries_path,
                )

        self.assertFalse(has_candidates)
        self.assertFalse(result["candidate_flag"].any())
        self.assertTrue(result["cluster"].isna().all())
        self.assertEqual(competitors, [])

    def test_prefers_configured_s3_gold(self) -> None:
        gold_parquet = io.BytesIO()
        gold_data().to_parquet(gold_parquet, index=False)
        boundaries_parquet = io.BytesIO()
        boundary_data().to_parquet(boundaries_parquet, index=False)
        competitors_parquet = io.BytesIO()
        competitor_data().to_parquet(competitors_parquet, index=False)
        gold_parquet.seek(0)
        boundaries_parquet.seek(0)
        competitors_parquet.seek(0)
        s3_client = unittest.mock.MagicMock()
        s3_client.get_object.side_effect = [
            {"Body": gold_parquet},
            {"Body": boundaries_parquet},
            {"Body": competitors_parquet},
        ]

        with (
            patch(
                "streamlit_data.get_storage_settings",
                return_value=SimpleNamespace(
                    bucket_name="test-bucket",
                    region_name="eu-west-1",
                ),
            ),
            patch("streamlit_data.boto3.client", return_value=s3_client),
        ):
            result, has_candidates, source, competitors = load_municipality_data(
                Path("missing-gold.parquet"),
                candidates_s3_key=None,
            )

        self.assertFalse(has_candidates)
        self.assertEqual(result["municipality_code"].tolist(), ["04001", "04002"])
        self.assertEqual(source, "S3 · gold/missing-gold.parquet")
        self.assertEqual(result.loc[0, "lat"], 36.5)
        self.assertEqual(len(competitors), 1)
        self.assertEqual(
            [call.kwargs["Key"] for call in s3_client.get_object.call_args_list],
            [
                "gold/missing-gold.parquet",
                "processed/silver/limites_municipales_andalucia.parquet",
                "processed/silver/gyms_with_municipality_andalusia.parquet",
            ],
        )

    def test_missing_s3_audit_does_not_fall_back_to_local_csv(self) -> None:
        s3_client = unittest.mock.MagicMock()
        s3_client.get_object.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "Not found"}},
            "GetObject",
        )

        with (
            patch(
                "streamlit_data.get_storage_settings",
                return_value=SimpleNamespace(
                    bucket_name="test-bucket",
                    region_name="eu-west-1",
                ),
            ),
            patch("streamlit_data.boto3.client", return_value=s3_client),
        ):
            with self.assertRaisesRegex(RuntimeError, "no se usa una copia local"):
                load_audit_sample()

    def test_loads_model_candidate_parquet_from_repository_s3_key(self) -> None:
        gold_parquet = io.BytesIO()
        gold_data().to_parquet(gold_parquet, index=False)
        boundaries_parquet = io.BytesIO()
        boundary_data().to_parquet(boundaries_parquet, index=False)
        competitors_parquet = io.BytesIO()
        competitor_data().to_parquet(competitors_parquet, index=False)
        candidates_parquet = io.BytesIO()
        candidate_data().to_parquet(candidates_parquet, index=False)
        gold_parquet.seek(0)
        boundaries_parquet.seek(0)
        competitors_parquet.seek(0)
        candidates_parquet.seek(0)
        s3_client = unittest.mock.MagicMock()
        s3_client.get_object.side_effect = [
            {"Body": gold_parquet},
            {"Body": boundaries_parquet},
            {"Body": competitors_parquet},
            {"Body": candidates_parquet},
        ]

        with (
            patch(
                "streamlit_data.get_storage_settings",
                return_value=SimpleNamespace(
                    bucket_name="test-bucket",
                    region_name="eu-west-1",
                ),
            ),
            patch("streamlit_data.boto3.client", return_value=s3_client),
        ):
            result, has_candidates, _, competitors = load_municipality_data(
                Path("missing-gold.parquet"),
            )

        self.assertTrue(has_candidates)
        self.assertEqual(result["candidate_flag"].tolist(), [True, False])
        self.assertEqual(result.loc[0, "cluster"], 2)
        self.assertTrue(pd.isna(result.loc[1, "cluster"]))
        self.assertEqual(len(competitors), 1)
        self.assertEqual(
            [call.kwargs["Key"] for call in s3_client.get_object.call_args_list],
            [
                "gold/missing-gold.parquet",
                "processed/silver/limites_municipales_andalucia.parquet",
                "processed/silver/gyms_with_municipality_andalusia.parquet",
                "results/municipios_candidatos.parquet",
            ],
        )

    def test_missing_s3_candidate_artifact_does_not_block_dashboard_data(self) -> None:
        gold_parquet = io.BytesIO()
        gold_data().to_parquet(gold_parquet, index=False)
        boundaries_parquet = io.BytesIO()
        boundary_data().to_parquet(boundaries_parquet, index=False)
        competitors_parquet = io.BytesIO()
        competitor_data().to_parquet(competitors_parquet, index=False)
        gold_parquet.seek(0)
        boundaries_parquet.seek(0)
        competitors_parquet.seek(0)
        s3_client = unittest.mock.MagicMock()
        s3_client.get_object.side_effect = [
            {"Body": gold_parquet},
            {"Body": boundaries_parquet},
            {"Body": competitors_parquet},
            ClientError(
                {
                    "Error": {
                        "Code": "NoSuchKey",
                        "Message": "The specified key does not exist.",
                    },
                    "ResponseMetadata": {"HTTPStatusCode": 404},
                },
                "GetObject",
            ),
        ]

        with (
            patch(
                "streamlit_data.get_storage_settings",
                return_value=SimpleNamespace(
                    bucket_name="test-bucket",
                    region_name="eu-west-1",
                ),
            ),
            patch("streamlit_data.boto3.client", return_value=s3_client),
        ):
            result, has_candidates, source, competitors = load_municipality_data(
                Path("missing-gold.parquet")
            )

        self.assertFalse(has_candidates)
        self.assertEqual(source, "S3 · gold/missing-gold.parquet")
        self.assertEqual(result["candidate_flag"].tolist(), [False, False])
        self.assertTrue(result["cluster"].isna().all())
        self.assertEqual(len(competitors), 1)

    def test_s3_candidate_access_errors_are_not_treated_as_missing_artifacts(self) -> None:
        gold_parquet = io.BytesIO()
        gold_data().to_parquet(gold_parquet, index=False)
        boundaries_parquet = io.BytesIO()
        boundary_data().to_parquet(boundaries_parquet, index=False)
        competitors_parquet = io.BytesIO()
        competitor_data().to_parquet(competitors_parquet, index=False)
        for buffer in (gold_parquet, boundaries_parquet, competitors_parquet):
            buffer.seek(0)
        s3_client = unittest.mock.MagicMock()
        s3_client.get_object.side_effect = [
            {"Body": gold_parquet},
            {"Body": boundaries_parquet},
            {"Body": competitors_parquet},
            ClientError(
                {
                    "Error": {
                        "Code": "AccessDenied",
                        "Message": "Access denied.",
                    },
                    "ResponseMetadata": {"HTTPStatusCode": 403},
                },
                "GetObject",
            ),
        ]

        with (
            patch(
                "streamlit_data.get_storage_settings",
                return_value=SimpleNamespace(
                    bucket_name="test-bucket",
                    region_name="eu-west-1",
                ),
            ),
            patch("streamlit_data.boto3.client", return_value=s3_client),
            self.assertRaisesRegex(RuntimeError, "denegó la lectura"),
        ):
            load_municipality_data(Path("missing-gold.parquet"))

    def test_reports_missing_s3_credentials_without_local_fallback(self) -> None:
        s3_client = unittest.mock.MagicMock()
        s3_client.get_object.side_effect = NoCredentialsError()

        with TemporaryDirectory() as directory:
            gold_path = Path(directory) / "gold.parquet"
            boundaries_path = Path(directory) / "boundaries.parquet"
            gold_data().to_parquet(gold_path, index=False)
            boundary_data().to_parquet(boundaries_path, index=False)

            with (
                patch(
                    "streamlit_data.get_storage_settings",
                    return_value=SimpleNamespace(
                        bucket_name="test-bucket",
                        region_name=None,
                    ),
                ),
                patch("streamlit_data.boto3.client", return_value=s3_client),
                self.assertRaisesRegex(RuntimeError, "No hay credenciales AWS"),
            ):
                load_municipality_data(gold_path, boundaries_path=boundaries_path)


if __name__ == "__main__":
    unittest.main()
