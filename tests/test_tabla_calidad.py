from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from src.common.storage import StorageSettings
from src.procesado.tabla_calidad import (
    create_and_upload_quality_table,
    create_quality_table,
)


def quality_inputs() -> dict[str, pd.DataFrame]:
    population_bronze = pd.DataFrame(
        {
            "Municipios": [
                "04001 Abla",
                "04002 Abrucena",
                "04002 Abrucena",
                "",
            ],
            "Periodo": ["2024", "2024", "2024", "2024"],
            "Sexo": ["Total"] * 4,
            "Edad": ["Todas las edades"] * 4,
            "Total": ["100", "200", "200", "0"],
        }
    )
    population_cleaned = pd.DataFrame(
        {
            "municipality_code": ["04001", "04002"],
            "year": [2024, 2024],
            "population_total": [100, 200],
            "population_18_50": [40, 80],
        }
    )
    income_bronze = pd.DataFrame(
        {
            "Municipios": ["04001 Abla", "04002 Abrucena", "04003 Adra"],
            "Periodo": ["2024"] * 3,
            "Distritos": [""] * 3,
            "Secciones": [""] * 3,
            "Indicadores de renta media": [
                "Renta neta media por persona"
            ] * 3,
            "Total": ["10000", "12000", "15000"],
        }
    )
    income_cleaned = pd.DataFrame(
        {
            "municipality_code": ["04001"],
            "year": [2024],
            "mean_net_income_per_person": [10000],
        }
    )
    gyms_bronze = pd.DataFrame(
        {
            "osm_type": ["node", "node", "node"],
            "osm_id": ["1", "2", "2"],
            "latitude": ["36.0", "36.1", "36.1"],
            "longitude": ["-3.0", "-3.1", "-3.1"],
        }
    )
    gyms_cleaned = pd.DataFrame(
        {
            "osm_type": ["node", "node"],
            "osm_id": ["1", "2"],
            "latitude": [36.0, 36.1],
            "longitude": [-3.0, -3.1],
            "sport_centre_type": ["gym", "gym"],
        }
    )
    gyms_with_municipality = pd.DataFrame(
        {
            "osm_type": ["node", "node"],
            "osm_id": ["1", "2"],
            "municipality_code": ["04001", None],
            "sport_centre_type": ["gym", "gym"],
        }
    )
    cnig_bronze = pd.DataFrame(
        {
            "nationalCode": ["34010404001", "34010404002"],
            "geometry": ["{}", "{}"],
        }
    )
    cnig_cleaned = pd.DataFrame(
        {
            "municipality_code": ["04001", "04002"],
            "geometry": ["geometry-a", "geometry-b"],
        }
    )
    gold_municipalities = pd.DataFrame(
        {
            "municipality_code": ["04001"],
            "income_year": [2024],
            "mean_net_income_per_person": [10000],
        }
    )
    return {
        "population_bronze": population_bronze,
        "population_cleaned": population_cleaned,
        "income_bronze": income_bronze,
        "income_cleaned": income_cleaned,
        "gyms_bronze": gyms_bronze,
        "gyms_cleaned": gyms_cleaned,
        "cnig_bronze": cnig_bronze,
        "cnig_cleaned": cnig_cleaned,
        "gyms_with_municipality": gyms_with_municipality,
        "gold_municipalities": gold_municipalities,
    }


class QualityTableTests(unittest.TestCase):
    def test_reports_raw_quality_filter_retention_and_crossing(self) -> None:
        report = create_quality_table(**quality_inputs()).set_index("source")

        self.assertEqual(len(report), 4)
        self.assertEqual(report.loc["Population", "records"], 4)
        self.assertEqual(report.loc["Population", "records_with_null_key"], 1)
        self.assertEqual(report.loc["Population", "duplicate_records"], 1)
        self.assertEqual(report.loc["Population", "records_crossed"], 1)
        self.assertEqual(report.loc["Population", "records_not_crossed"], 1)
        self.assertEqual(report.loc["Population", "cross_pct"], 50.0)

        self.assertEqual(report.loc["Income", "candidate_municipalities"], 3)
        self.assertEqual(report.loc["Income", "cleaned_municipalities"], 1)
        self.assertAlmostEqual(
            report.loc["Income", "municipality_retention_pct"],
            100 / 3,
        )
        self.assertEqual(report.loc["Income", "records_crossed"], 1)
        self.assertEqual(report.loc["Income", "cross_pct"], 100.0)
        self.assertIn(
            "2 códigos municipales candidatos",
            report.loc["Income", "decision_adopted"],
        )

        self.assertEqual(report.loc["Gyms (OSM)", "duplicate_records"], 1)
        self.assertEqual(report.loc["Gyms (OSM)", "records_not_crossed"], 1)
        self.assertEqual(report.loc["CNIG boundaries", "records_crossed"], 1)
        self.assertEqual(report.loc["CNIG boundaries", "records_not_crossed"], 1)

    def test_uploads_quality_report_to_processed_quality_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "quality.parquet"
            with (
                patch(
                    "src.procesado.tabla_calidad.get_storage_settings",
                    return_value=StorageSettings(
                        True,
                        True,
                        "test-bucket",
                        "eu-test-1",
                    ),
                ),
                patch(
                    "src.procesado.tabla_calidad.QUALITY_TABLE_PATH",
                    output_path,
                ),
                patch("src.procesado.tabla_calidad.upload_files_to_s3") as upload,
            ):
                report = create_and_upload_quality_table(**quality_inputs())

            restored = pd.read_parquet(output_path)
            self.assertEqual(len(restored), len(report))
            self.assertEqual(restored["source"].tolist(), report["source"].tolist())
            upload.assert_called_once_with(
                [output_path],
                prefix="processed/quality",
                bucket_name="test-bucket",
                region_name="eu-test-1",
            )


if __name__ == "__main__":
    unittest.main()
