import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd

from src.negocio import ejecutar


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

            with (
                patch.object(ejecutar, "ORO", gold_path),
                patch.object(ejecutar, "CLUSTER_ASSIGNMENTS_PATH", clusters_path),
                patch.object(ejecutar, "get_storage_settings", return_value=settings),
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

            with (
                patch.object(ejecutar, "ORO", gold_path),
                patch.object(ejecutar, "CLUSTER_ASSIGNMENTS_PATH", clusters_path),
                patch.object(ejecutar, "get_storage_settings", return_value=settings),
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

        with (
            patch.object(ejecutar, "ORO", Path("gold.parquet")),
            patch.object(
                ejecutar,
                "CLUSTER_ASSIGNMENTS_PATH",
                Path("clusters.parquet"),
            ),
            patch.object(ejecutar, "get_storage_settings", return_value=settings),
            patch.object(
                ejecutar,
                "s3_uri_for",
                side_effect=lambda filename, prefix: (
                    f"s3://test-bucket/{prefix}/{filename}"
                ),
            ),
            patch.object(ejecutar.boto3, "client", return_value=s3_client),
        ):
            datos = ejecutar.cargar()

        self.assertEqual(datos["municipality_code"].tolist(), ["00001", "00003"])
        self.assertEqual(s3_client.get_object.call_count, 2)


if __name__ == "__main__":
    unittest.main()
