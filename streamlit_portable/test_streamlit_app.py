from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

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
        self.assertNotIn("__MARKET__", html)
        self.assertNotIn("__ANALYSIS__", html)

    def test_static_assets_match_integrated_portable2_files(self) -> None:
        web_dir = Path(__file__).resolve().parent / "web"
        expected_hashes = {
            "streamlit.html": "013645e16bbc63e76fdc40ec98d318854d3ac1e805a0f5f33d8a8e39d985c898",
            "streamlit.css": "7cac206662c387b06a3134db7de68f98ffef33e9adb43d7ecec24e2e2328b638",
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
