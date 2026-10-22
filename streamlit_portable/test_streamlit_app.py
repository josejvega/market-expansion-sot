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
            has_clusters=False,
            gold_source="S3 · gold/tabla_oro_municipios_andalucia.parquet",
        )

        self.assertEqual(study["schema_version"], 1)
        self.assertEqual(len(study["baseline"]), 5)
        first = study["municipalities"][0]
        self.assertAlmostEqual(first["lat"], 36.05)
        self.assertAlmostEqual(first["lon"], -1.95)
        self.assertIsNone(first["score"])
        self.assertIsNone(first["tourism_beds"])
        self.assertEqual(validate_study(study), study)

    def test_renders_portable2_layout_with_live_repository_data(self) -> None:
        study = build_study(
            self.municipalities,
            has_clusters=False,
            gold_source="S3 · gold/tabla_oro_municipios_andalucia.parquet",
        )

        html = render_study(study)

        self.assertIn("tab-situation", html)
        self.assertIn("tab-intelligence", html)
        self.assertIn("tab-decision", html)
        self.assertIn("Simulador de escenarios", html)
        self.assertIn("Secciones censales y areas de influencia", html)
        self.assertIn("marketAnalysis.simulate", html)
        self.assertIn('"lat": 36.05', html)
        self.assertIn('"lon": -1.95', html)
        self.assertNotIn("__DATA__", html)
        self.assertNotIn("__MARKET__", html)
        self.assertNotIn("__ANALYSIS__", html)

    def test_static_assets_are_exact_portable2_files(self) -> None:
        web_dir = Path(__file__).resolve().parent / "web"
        expected_hashes = {
            "streamlit.html": "5bd5b96c544d830f33b887486b2d14d790686665be49a2286426ab1f285882d5",
            "streamlit.css": "7cac206662c387b06a3134db7de68f98ffef33e9adb43d7ecec24e2e2328b638",
            "streamlit_analysis.js": "36cef0726e1bfade683f99f42e7a9249147966db4c5db700b189a908f95bd56d",
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
