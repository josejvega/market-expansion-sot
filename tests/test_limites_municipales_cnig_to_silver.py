from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
import pandas as pd
from shapely.geometry import MultiPolygon, box

from src.common.storage import StorageSettings
from src.procesado.limpiar_limites_municipales import (
    OUTPUT_COLUMNS,
    clean_municipality_boundaries,
    clean_municipality_boundaries_from_csv,
)
from src.procesado.pipeline import clean_and_upload_municipality_boundaries


LOADED_AT_UTC = "2026-10-20T07:00:00+00:00"


def boundaries_source() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "cnig_national_code": ["34010404001", "34011414001", "34010101001"],
            "cnig_name": [" Abla ", "Córdoba", "Municipio fuera de Andalucía"],
            "ine_code": ["04001", "14001", "01001"],
        },
        geometry=[
            MultiPolygon([box(-2.0, 36.0, -1.9, 36.1)]),
            MultiPolygon([box(-4.9, 37.8, -4.8, 37.9)]),
            MultiPolygon([box(-2.0, 42.5, -1.9, 42.6)]),
        ],
        crs="EPSG:4326",
    )


class MunicipalityBoundariesTests(unittest.TestCase):
    def test_clean_filters_and_normalizes_andalusian_municipalities(self) -> None:
        result = clean_municipality_boundaries(
            boundaries_source(),
            loaded_at_utc=LOADED_AT_UTC,
            failed_output_path=None,
        )

        self.assertEqual(list(result.columns), OUTPUT_COLUMNS)
        self.assertEqual(result["municipality_code"].tolist(), ["04001", "14001"])
        self.assertEqual(result.iloc[0]["municipality_name"], "Abla")
        self.assertTrue(result["source"].eq("IGN/CNIG BDDAE").all())
        self.assertTrue(result["loaded_at_utc"].eq(pd.Timestamp(LOADED_AT_UTC)).all())
        self.assertEqual(result.crs.to_epsg(), 4326)
        self.assertTrue(result.geometry.geom_type.eq("MultiPolygon").all())

    def test_clean_rejects_exact_duplicates_and_conflicting_municipalities(self) -> None:
        one_row = boundaries_source().iloc[[0]]
        with tempfile.TemporaryDirectory() as temporary_directory:
            failed_path = Path(temporary_directory) / "municipalities_failed.parquet"
            exact_duplicates = gpd.GeoDataFrame(
                pd.concat([one_row, one_row], ignore_index=True),
                geometry="geometry",
                crs="EPSG:4326",
            )
            cleaned = clean_municipality_boundaries(
                exact_duplicates,
                loaded_at_utc=LOADED_AT_UTC,
                failed_output_path=failed_path,
            )
            self.assertEqual(cleaned["municipality_code"].tolist(), ["04001"])
            rejected = gpd.read_parquet(failed_path)
            self.assertEqual(len(rejected), 1)
            self.assertEqual(
                rejected.iloc[0]["failure_reason"],
                "Exact duplicate record",
            )

            conflicting = one_row.copy()
            conflicting["cnig_name"] = "Different name"
            conflicting = gpd.GeoDataFrame(
                pd.concat([one_row, conflicting], ignore_index=True),
                geometry="geometry",
                crs="EPSG:4326",
            )
            cleaned = clean_municipality_boundaries(
                conflicting,
                loaded_at_utc=LOADED_AT_UTC,
                failed_output_path=failed_path,
            )
            rejected = gpd.read_parquet(failed_path)

        self.assertTrue(cleaned.empty)
        self.assertEqual(len(rejected), 2)
        self.assertTrue(
            rejected["failure_reason"]
            .str.contains("Conflicting duplicate municipality code")
            .all()
        )

    def test_clean_rejects_null_values_and_inconsistent_codes(self) -> None:
        null_name = boundaries_source().iloc[[0]].copy()
        null_name.loc[null_name.index[0], "cnig_name"] = None
        with tempfile.TemporaryDirectory() as temporary_directory:
            failed_path = Path(temporary_directory) / "municipalities_failed.parquet"
            clean_municipality_boundaries(
                null_name,
                loaded_at_utc=LOADED_AT_UTC,
                failed_output_path=failed_path,
            )
            rejected = gpd.read_parquet(failed_path)
            self.assertIn(
                "Missing required value: cnig_name",
                rejected.iloc[0]["failure_reason"],
            )

        mismatched_code = boundaries_source().iloc[[0]].copy()
        mismatched_code.loc[
            mismatched_code.index[0], "cnig_national_code"
        ] = "34010404002"
        with tempfile.TemporaryDirectory() as temporary_directory:
            failed_path = Path(temporary_directory) / "municipalities_failed.parquet"
            clean_municipality_boundaries(
                mismatched_code,
                loaded_at_utc=LOADED_AT_UTC,
                failed_output_path=failed_path,
            )
            rejected = gpd.read_parquet(failed_path)
            self.assertIn(
                "does not end with municipality code",
                rejected.iloc[0]["failure_reason"],
            )

    def test_clean_from_csv_saves_silver_parquet(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            source_path = temporary_path / "source.csv"
            output_path = temporary_path / "result.parquet"
            failed_path = temporary_path / "municipalities_failed.parquet"
            source = boundaries_source().iloc[[0, 1]]
            source_csv = pd.DataFrame(
                {
                    "nationalCode": source["cnig_national_code"].tolist()
                    + ["34010404003"],
                    "name": source["cnig_name"].tolist() + ["Bad geometry"],
                    "geometry": [
                        json.dumps(geometry.__geo_interface__)
                        for geometry in source.geometry
                    ]
                    + ["{invalid-json"],
                }
            )
            source_csv.to_csv(source_path, index=False)

            result_path = clean_municipality_boundaries_from_csv(
                source_path,
                output_path,
                failed_path,
            )

            self.assertEqual(result_path, output_path)
            restored = gpd.read_parquet(output_path)
            self.assertEqual(len(restored), 2)
            self.assertEqual(list(restored.columns), OUTPUT_COLUMNS)
            self.assertEqual(restored.crs.to_epsg(), 4326)
            rejected = gpd.read_parquet(failed_path)
            self.assertEqual(len(rejected), 1)
            self.assertEqual(rejected.iloc[0]["nationalCode"], "34010404003")
            self.assertEqual(
                rejected.iloc[0]["failure_reason"],
                "Invalid GeoJSON geometry",
            )

    def test_cnig_s3_only_cleaning_stages_then_removes_silver_output(self) -> None:
        source = boundaries_source().iloc[[0]]
        raw_csv = pd.DataFrame(
            {
                "nationalCode": source["cnig_national_code"].tolist(),
                "name": source["cnig_name"].tolist(),
                "geometry": [
                    json.dumps(geometry.__geo_interface__)
                    for geometry in source.geometry
                ],
            }
        )
        uploaded_paths: list[Path] = []

        def fake_upload(paths: list[Path], **_: object) -> list[str]:
            uploaded_paths.extend(paths)
            self.assertTrue(all(path.is_file() for path in paths))
            return []

        with (
            patch(
                "src.procesado.pipeline.get_storage_settings",
                return_value=StorageSettings(False, True, "test-bucket", "eu-test-1"),
            ),
            patch(
                "src.procesado.pipeline.upload_files_to_s3",
                side_effect=fake_upload,
            ),
        ):
            cleaned = clean_and_upload_municipality_boundaries(raw_csv)

        self.assertEqual(cleaned["municipality_code"].tolist(), ["04001"])
        self.assertEqual(
            {path.name for path in uploaded_paths},
            {
                "limites_municipales_andalucia.parquet",
                "limites_municipales_andalucia_failed.parquet",
            },
        )
        self.assertTrue(all(not path.exists() for path in uploaded_paths))


if __name__ == "__main__":
    unittest.main()
