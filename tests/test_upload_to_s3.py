from __future__ import annotations

import io
import tempfile
import unittest
import os
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from botocore.exceptions import ClientError, NoCredentialsError

from src.common.storage import StorageSettings, _read_bool_setting, read_csv_dataset
from src.common.upload_to_s3 import upload_files_to_s3
from src.ingesta.pipeline import download_and_upload_population
from src.procesado import pipeline as processing_pipeline


class UploadToS3Tests(unittest.TestCase):
    def test_batch_upload_uses_bucket_and_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            local_file = Path(temporary_directory) / "population_andalusia.csv"
            local_file.write_text("municipality\nAbla\n", encoding="utf-8")
            with patch("src.common.upload_to_s3.boto3.client") as create_client:
                uris = upload_files_to_s3(
                    [local_file],
                    bucket_name="example-bucket",
                    prefix="raw/data",
                    region_name="eu-west-1",
                )

        create_client.assert_called_once_with("s3", region_name="eu-west-1")
        create_client.return_value.upload_file.assert_called_once_with(
            str(local_file),
            "example-bucket",
            "raw/data/population_andalusia.csv",
        )
        self.assertEqual(
            uris,
            ["s3://example-bucket/raw/data/population_andalusia.csv"],
        )

    def test_batch_upload_reads_bucket_from_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            local_file = Path(temporary_directory) / "population_andalusia.csv"
            local_file.write_text("municipality\nAbla\n", encoding="utf-8")
            with (
                patch.dict(os.environ, {"S3_BUCKET": "test-bucket"}),
                patch("src.common.upload_to_s3.boto3.client") as create_client,
            ):
                uris = upload_files_to_s3([local_file], prefix="raw/data")

        create_client.assert_called_once_with("s3")
        create_client.return_value.upload_file.assert_called_once_with(
            str(local_file),
            "test-bucket",
            "raw/data/population_andalusia.csv",
        )
        self.assertEqual(
            uris,
            ["s3://test-bucket/raw/data/population_andalusia.csv"],
        )

    def test_batch_upload_warns_when_bucket_is_not_configured(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            local_file = Path(temporary_directory) / "population.csv"
            local_file.write_text("municipality\nAbla\n", encoding="utf-8")
            with (
                patch.dict(os.environ, {"S3_BUCKET": ""}),
                patch("src.common.upload_to_s3.load_dotenv"),
                patch("src.common.upload_to_s3.boto3.client") as create_client,
            ):
                with self.assertLogs("src.common.upload_to_s3", level="WARNING") as logs:
                    uploaded = upload_files_to_s3([local_file])

            create_client.assert_not_called()
            self.assertTrue(local_file.is_file())

        self.assertEqual(uploaded, [])
        self.assertIn("S3_BUCKET is not configured", logs.output[0])

    def test_batch_upload_warns_and_continues_after_s3_upload_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            first_file = Path(temporary_directory) / "first.csv"
            second_file = Path(temporary_directory) / "second.csv"
            first_file.write_text("first", encoding="utf-8")
            second_file.write_text("second", encoding="utf-8")
            with patch("src.common.upload_to_s3.boto3.client") as create_client:
                create_client.return_value.upload_file.side_effect = [
                    ClientError(
                        {
                            "Error": {"Code": "AccessDenied", "Message": "denied"},
                            "ResponseMetadata": {"HTTPStatusCode": 403},
                        },
                        "PutObject",
                    ),
                    None,
                ]
                with self.assertLogs("src.common.upload_to_s3", level="WARNING") as logs:
                    uploaded = upload_files_to_s3(
                        [first_file, second_file],
                        bucket_name="example-bucket",
                        prefix="raw/data",
                    )
            self.assertTrue(first_file.is_file())
            self.assertTrue(second_file.is_file())

        self.assertEqual(
            uploaded,
            ["s3://example-bucket/raw/data/second.csv"],
        )
        self.assertEqual(create_client.return_value.upload_file.call_count, 2)
        self.assertIn("local file was kept", logs.output[0])

    def test_batch_upload_warns_if_s3_client_cannot_be_created(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            local_file = Path(temporary_directory) / "population.csv"
            local_file.write_text("municipality\nAbla\n", encoding="utf-8")
            with patch(
                "src.common.upload_to_s3.boto3.client",
                side_effect=NoCredentialsError(),
            ):
                with self.assertLogs("src.common.upload_to_s3", level="WARNING") as logs:
                    uploaded = upload_files_to_s3([local_file])
            self.assertTrue(local_file.is_file())

        self.assertEqual(uploaded, [])
        self.assertIn("local files were kept", logs.output[0])


class StoragePipelineTests(unittest.TestCase):
    def test_boolean_settings_accept_common_values_and_reject_invalid_values(self) -> None:
        with patch.dict(os.environ, {"SAVE_LOCALLY": "yes"}):
            self.assertTrue(_read_bool_setting("SAVE_LOCALLY", False))
        with patch.dict(os.environ, {"SAVE_S3": "0"}):
            self.assertFalse(_read_bool_setting("SAVE_S3", True))
        with patch.dict(os.environ, {"SAVE_S3": "sometimes"}):
            with self.assertRaisesRegex(ValueError, "SAVE_S3"):
                _read_bool_setting("SAVE_S3", False)

    def test_s3_only_csv_reader_prefers_s3_over_a_stale_local_copy(self) -> None:
        response = {"Body": io.BytesIO(b"municipality,value\nAbla,1\n")}
        with tempfile.TemporaryDirectory() as directory:
            local_path = Path(directory) / "population.csv"
            local_path.write_text("municipality,value\nStale,0\n", encoding="utf-8")
            with (
                patch(
                    "src.common.storage.get_storage_settings",
                    return_value=StorageSettings(
                        False,
                        True,
                        "test-bucket",
                        "eu-test-1",
                    ),
                ),
                patch("src.common.storage.boto3.client") as s3_client,
            ):
                s3_client.return_value.get_object.return_value = response
                result = read_csv_dataset(
                    local_path,
                    "s3://test-bucket/raw/data/population.csv",
                )

        self.assertEqual(
            result.to_dict("records"),
            [{"municipality": "Abla", "value": 1}],
        )
        s3_client.return_value.get_object.assert_called_once_with(
            Bucket="test-bucket",
            Key="raw/data/population.csv",
        )

    def test_csv_reader_falls_back_to_local_when_s3_is_not_accessible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            local_path = Path(directory) / "population.csv"
            local_path.write_text("municipality,value\nAbla,1\n", encoding="utf-8")
            with (
                patch(
                    "src.common.storage.get_storage_settings",
                    return_value=StorageSettings(
                        False,
                        True,
                        "test-bucket",
                        "eu-test-1",
                    ),
                ),
                patch(
                    "src.common.storage.boto3.client"
                ) as s3_client,
                self.assertLogs("src.common.storage", level="WARNING") as logs,
            ):
                s3_client.return_value.get_object.side_effect = ClientError(
                    {
                        "Error": {"Code": "AccessDenied", "Message": "denied"},
                        "ResponseMetadata": {"HTTPStatusCode": 403},
                    },
                    "GetObject",
                )
                result = read_csv_dataset(
                    local_path,
                    "s3://test-bucket/raw/data/population.csv",
                )

        self.assertEqual(
            result.to_dict("records"),
            [{"municipality": "Abla", "value": 1}],
        )
        self.assertIn("falling back to local file", logs.output[0])

    def test_csv_reader_raises_if_s3_and_local_fallback_are_unavailable(self) -> None:
        missing_path = Path("missing-population.csv")
        with (
            patch(
                "src.common.storage.get_storage_settings",
                return_value=StorageSettings(
                    False,
                    True,
                    "test-bucket",
                    "eu-test-1",
                ),
            ),
            patch(
                "src.common.storage.boto3.client"
            ) as s3_client,
        ):
            s3_client.return_value.get_object.side_effect = ClientError(
                {
                    "Error": {"Code": "NoSuchKey", "Message": "missing"},
                    "ResponseMetadata": {"HTTPStatusCode": 404},
                },
                "GetObject",
            )
            with self.assertRaisesRegex(
                RuntimeError,
                "no local fallback exists",
            ):
                read_csv_dataset(
                    missing_path,
                    "s3://test-bucket/raw/data/population.csv",
                )

    def test_s3_only_ingestion_uses_and_cleans_temporary_output(self) -> None:
        uploaded_path: Path | None = None

        def fake_download(output_dir: Path, **_: object) -> Path:
            nonlocal uploaded_path
            uploaded_path = output_dir / "population_andalusia.csv"
            uploaded_path.write_text("municipality\nAbla\n", encoding="utf-8")
            return uploaded_path

        with (
            patch(
                "src.ingesta.pipeline.get_storage_settings",
                return_value=StorageSettings(False, True, "test-bucket", "eu-test-1"),
            ),
            patch(
                "src.ingesta.pipeline.download_andalusia_population_by_municipality_from_ine",
                side_effect=fake_download,
            ),
            patch(
                "src.ingesta.pipeline.upload_files_to_s3",
                return_value=["s3://test-bucket/raw/data/population_andalusia.csv"],
            ) as upload,
        ):
            result = download_and_upload_population()

        self.assertEqual(
            result,
            "s3://test-bucket/raw/data/population_andalusia.csv",
        )
        self.assertIsNotNone(uploaded_path)
        self.assertFalse(uploaded_path.exists())
        upload.assert_called_once()
        self.assertEqual(upload.call_args.kwargs["prefix"], "raw/data")

    def test_s3_only_cleaning_uploads_staged_silver_and_failed_files(self) -> None:
        uploaded_paths: list[Path] = []

        def fake_cleaner(
            source: pd.DataFrame,
            failed_output_path: Path | None,
        ) -> pd.DataFrame:
            self.assertIsNotNone(failed_output_path)
            failed_output_path.write_text("failed rows", encoding="utf-8")
            return source.copy()

        def fake_upload(paths: list[Path], **_: object) -> list[str]:
            uploaded_paths.extend(paths)
            self.assertTrue(all(path.is_file() for path in paths))
            return []

        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "src.procesado.pipeline.get_storage_settings",
                return_value=StorageSettings(False, True, "test-bucket", "eu-test-1"),
            ),
            patch(
                "src.procesado.pipeline.POPULATION_SILVER_PATH",
                Path(directory) / "population_andalusia.parquet",
            ),
            patch(
                "src.procesado.pipeline.POPULATION_FAILED_PATH",
                Path(directory) / "population_failed.parquet",
            ),
            patch(
                "src.procesado.pipeline.clean_population",
                side_effect=fake_cleaner,
            ),
            patch(
                "src.procesado.pipeline.upload_files_to_s3",
                side_effect=fake_upload,
            ),
        ):
            result = processing_pipeline.clean_and_upload_population(
                pd.DataFrame({"value": [1]})
            )

        self.assertEqual(result["value"].tolist(), [1])
        self.assertEqual(len(uploaded_paths), 2)
        self.assertTrue(all(not path.exists() for path in uploaded_paths))

    def test_local_only_cleaning_persists_outputs_without_uploading(self) -> None:
        def fake_cleaner(
            source: pd.DataFrame,
            failed_output_path: Path | None,
        ) -> pd.DataFrame:
            self.assertIsNotNone(failed_output_path)
            failed_output_path.write_text("failed rows", encoding="utf-8")
            return source.copy()

        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "src.procesado.pipeline.get_storage_settings",
                return_value=StorageSettings(True, False, None, None),
            ),
            patch(
                "src.procesado.pipeline.POPULATION_SILVER_PATH",
                Path(directory) / "population_andalusia.parquet",
            ),
            patch(
                "src.procesado.pipeline.POPULATION_FAILED_PATH",
                Path(directory) / "population_failed.parquet",
            ),
            patch(
                "src.procesado.pipeline.clean_population",
                side_effect=fake_cleaner,
            ),
            patch("src.procesado.pipeline.upload_files_to_s3") as upload,
        ):
            result = processing_pipeline.clean_and_upload_population(
                pd.DataFrame({"value": [1]})
            )
            self.assertTrue(
                (Path(directory) / "population_andalusia.parquet").is_file()
            )
            self.assertTrue((Path(directory) / "population_failed.parquet").is_file())

        self.assertEqual(result["value"].tolist(), [1])
        upload.assert_not_called()


if __name__ == "__main__":
    unittest.main()
