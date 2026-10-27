from __future__ import annotations

import hashlib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import geopandas as gpd
import pandas as pd
from shapely.geometry import Polygon

from streamlit_app import build_study, render_study
from streamlit_data import (
    add_municipality_coordinates,
    prepare_municipality_data,
    validate_study,
)


class Portable2DashboardTests(unittest.TestCase):
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
                "population_18_50": [
                    100000,
                    120000,
                    140000,
                    160000,
                    180000,
                    200000,
                ],
                "population_growth_pct": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
                "mean_net_income_per_person": [
                    18000,
                    19000,
                    20000,
                    21000,
                    22000,
                    23000,
                ],
                "gyms_per_10k_18_50": [0.1, 0.09, 0.08, 0.07, 0.06, 0.05],
                "gyms_count": [1, 1, 1, 1, 1, 1],
                "other_sports_facilities_count": [0, 0, 0, 0, 0, 0],
                "population_year": [2024] * 6,
            }
        )
        self.municipalities, _ = prepare_municipality_data(gold)
        boundaries = gpd.GeoDataFrame(
            {
                "municipality_code": gold["municipality_code"],
                "geometry": [
                    Polygon(
                        [
                            (-2.0 + index * 0.1, 36.0),
                            (-1.9 + index * 0.1, 36.0),
                            (-1.9 + index * 0.1, 36.1),
                            (-2.0 + index * 0.1, 36.1),
                        ]
                    )
                    for index in range(len(gold))
                ],
            },
            crs="EPSG:4326",
        )
        self.municipalities = add_municipality_coordinates(
            self.municipalities,
            boundaries,
        )

    def test_builds_portable2_schema_from_gold_and_silver(self) -> None:
        study = build_study(
            self.municipalities,
            has_model_candidates=False,
            gold_source="S3 · gold/tabla_oro_municipios_andalucia.parquet",
        )

        self.assertEqual(study["schema_version"], 1)
        self.assertEqual(len(study["baseline"]), 5)
        expected_baseline = (
            self.municipalities.sort_values(
                ["population_18_50", "municipality_code"],
                ascending=[False, True],
            )["municipality_code"]
            .astype(str)
            .head(5)
            .tolist()
        )
        self.assertEqual(study["baseline"], expected_baseline)
        self.assertEqual(study["selection"], [])
        self.assertIn("falta el artefacto", study["metadata"]["selection_description"])
        self.assertEqual(
            study["metadata"]["missing_artifacts"],
            ["results/municipios_candidatos.parquet"],
        )
        first = study["municipalities"][0]
        self.assertAlmostEqual(first["lat"], 36.05)
        self.assertAlmostEqual(first["lon"], -1.95)
        self.assertIsNone(first["score"])
        self.assertIsNone(first["tourism_beds"])
        self.assertEqual(validate_study(study), study)

    def test_baseline_recalculates_when_gold_population_changes(self) -> None:
        municipalities = self.municipalities.copy()
        municipalities.loc[0, "population_18_50"] = 500000

        study = build_study(
            municipalities,
            has_model_candidates=False,
            gold_source="S3 · gold/tabla_oro_municipios_andalucia.parquet",
        )

        self.assertEqual(study["baseline"][0], "04001")

    def test_recommendation_uses_published_model_candidates(self) -> None:
        municipalities = self.municipalities.assign(
            cluster=pd.Series([0, 0, pd.NA, 1, pd.NA, pd.NA], dtype="Int64"),
            candidate_flag=[True, True, False, True, False, False],
        )

        study = build_study(
            municipalities,
            has_model_candidates=True,
            gold_source="S3 · gold/tabla_oro_municipios_andalucia.parquet",
        )

        self.assertEqual(validate_study(study), study)
        self.assertEqual(study["metadata"]["missing_artifacts"], [])
        self.assertNotIn('class="data-warning"', render_study(study))
        candidates = [
            row for row in study["municipalities"] if row["candidate"]
        ]
        self.assertGreater(len(candidates), 0)
        self.assertTrue(
            all("competencia ponderada" in row["reason"] for row in candidates)
        )
        self.assertEqual(
            [row["cluster"] for row in study["municipalities"]],
            [
                "0",
                "0",
                "Asignación no publicada",
                "1",
                "Asignación no publicada",
                "Asignación no publicada",
            ],
        )
        self.assertTrue(
            all(row["score"] is None for row in study["municipalities"])
        )

    def test_uses_published_business_selection_and_financials(self) -> None:
        municipalities = self.municipalities.assign(
            cluster=pd.Series([0, 0, pd.NA, 1, pd.NA, pd.NA], dtype="Int64"),
            candidate_flag=[True, True, False, True, False, False],
        )
        selection = pd.DataFrame(
            {
                "municipality_code": ["04001"],
                "municipality_name": ["Municipio 1"],
                "facturacion_anual": [123456.0],
                "demanda_por_comp": [456.0],
                "motivo_calidad": ["Publicada por el análisis de negocio"],
            }
        )
        baseline_ids = municipalities.sort_values(
            ["population_18_50", "municipality_code"],
            ascending=[False, True],
        ).head(5)
        baseline = baseline_ids.assign(
            facturacion_anual=100000.0,
            demanda_por_comp=200.0,
        )
        comparison = pd.DataFrame(
            {
                "estrategia": ["Baseline", "Modelo"],
                "centros_seleccionados": [5, 5],
                "centros_viables": [3, 5],
                "facturacion_operativa_total_eur": [2500000.0, 3400000.0],
                "margen_operativo_total_eur": [-100000.0, 600000.0],
                "perdidas_operativas_totales_eur": [300000.0, 0.0],
                "demanda_media_por_competidor": [900.0, 2100.0],
            }
        )
        robustness = pd.DataFrame(
            {
                "municipality_code": ["04001"],
                "municipality_name": ["Municipio 1"],
                "apariciones": [67],
                "posicion_media": [2.1],
                "robustez": ["67 de 108"],
                "combinaciones_totales": [108],
                "fact_min": [581908.0],
            }
        )

        study = build_study(
            municipalities,
            has_model_candidates=True,
            gold_source="S3 · gold/tabla_oro_municipios_andalucia.parquet",
            business_outputs={
                "selection": selection,
                "baseline": baseline,
                "comparison": comparison,
                "robustness": robustness,
            },
            business_source="S3 · results/negocio/",
        )

        self.assertEqual(study["selection"], ["04001"])
        self.assertEqual(study["baseline"], baseline_ids["municipality_code"].tolist())
        selected = next(
            row for row in study["municipalities"] if row["id"] == "04001"
        )
        self.assertEqual(selected["annual_revenue_eur"], 123456.0)
        self.assertEqual(selected["demand_per_competitor"], 456.0)
        self.assertEqual(selected["reason"], "Publicada por el análisis de negocio")
        self.assertEqual(study["metadata"]["business_kpis"][1]["viable"], 5)
        self.assertEqual(
            study["metadata"]["business_robustness"][0]["appearances"],
            67,
        )
        formulas = study["metadata"]["business_formulas"]
        self.assertTrue(
            any(
                item["label"] == "Facturación anual estimada"
                for item in formulas
            )
        )
        self.assertEqual(validate_study(study), study)
        html = render_study(study)
        self.assertIn('id="business-formulas"', html)
        self.assertIn("KPI y estabilidad de la recomendacion", html)
        self.assertIn('"business_kpis"', html)
        self.assertIn('"business_robustness"', html)
        self.assertNotIn("<th>Score</th>", html)

    def test_renders_portable2_layout_with_live_repository_data(self) -> None:
        study = build_study(
            self.municipalities,
            has_model_candidates=False,
            gold_source="S3 · gold/tabla_oro_municipios_andalucia.parquet",
        )

        html = render_study(study)

        self.assertIn("tab-situation", html)
        self.assertIn("tab-intelligence", html)
        self.assertIn("tab-decision", html)
        self.assertIn("Simulador de escenarios", html)
        self.assertIn("Secciones censales y areas de influencia", html)
        self.assertIn("marketAnalysis.simulate", html)
        self.assertRegex(html, r"<style>\s*:root\{--ink:")
        self.assertIn("--accent:#a100ff", html)
        self.assertNotIn("\ufeff", html)
        self.assertIn('"lat": 36.05', html)
        self.assertIn('"lon": -1.95', html)
        self.assertNotIn("__DATA__", html)
        self.assertIn('class="data-warning" role="status"', html)
        self.assertIn("results/municipios_candidatos.parquet", html)
        self.assertIn("El resto del dashboard se carga", html)
        self.assertLess(html.index('class="data-warning"'), html.index("<header>"))
        self.assertNotIn("__MARKET__", html)
        self.assertNotIn("__ANALYSIS__", html)

    def test_renders_manual_competitor_audit_sample(self) -> None:
        audit = [
            {
                "name": "Club",
                "municipality_name": "Municipio 1",
                "status": "needs_confirmation",
                "finding": "Confirmar actividad actual.",
                "evidence_url": "https://example.com/club",
                "checked_date": "2026-10-26",
            }
        ]
        study = build_study(
            self.municipalities,
            has_model_candidates=False,
            gold_source="Local · Gold",
            audit=audit,
            audit_source="S3 · results/negocio/auditoria_20_gimnasios.csv",
        )

        self.assertEqual(validate_study(study), study)
        html = render_study(study)
        self.assertIn('"audit_source":', html)
        self.assertIn('"name": "Club"', html)
        self.assertIn("needsConfirmation", html)
        self.assertIn("Requiere confirmación adicional", html)

    def test_static_assets_match_integrated_portable2_files(self) -> None:
        web_dir = Path(__file__).resolve().parent / "web"
        expected_hashes = {
            "streamlit.html": "72454e86fdc927450a45ba1ed64dafeb38ec7583a9e9a493792cae3c06e6fe2b",
            "streamlit.css": "888cbb72656dda6aeda0bd3124646f80c2a0a522c4bbbf1f225b8d39eed35375",
            "streamlit_analysis.js": "df7e560b61b16f0d4a40264162d941cfaf7111782d40efcdb3d80fdffb5fb13e",
        }

        for filename, expected_hash in expected_hashes.items():
            with self.subTest(filename=filename):
                actual_hash = hashlib.sha256((web_dir / filename).read_bytes()).hexdigest()
                self.assertEqual(actual_hash, expected_hash)

    def test_streamlit_theme_is_explicitly_light(self) -> None:
        config_path = Path(__file__).resolve().parents[1] / ".streamlit" / "config.toml"

        self.assertEqual(
            config_path.read_text(encoding="utf-8"),
            '[theme]\nbase = "light"\nprimaryColor = "#a100ff"\n'
            'backgroundColor = "#faf9fc"\nsecondaryBackgroundColor = "#ffffff"\n'
            'textColor = "#17151b"\n',
        )


if __name__ == "__main__":
    unittest.main()
