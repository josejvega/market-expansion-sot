from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from botocore.exceptions import ClientError

from upload_to_s3 import parse_s3_uri, upload_file_to_s3


class FakeS3Client:
    def __init__(self, object_exists: bool = False) -> None:
        self.object_exists = object_exists
        self.upload_arguments: dict[str, object] = {}
        self.uploaded_body: bytes | None = None

    def put_object(self, **arguments: object) -> dict[str, str]:
        self.upload_arguments = arguments
        if self.object_exists:
            raise ClientError(
                {
                    "Error": {"Code": "PreconditionFailed"},
                    "ResponseMetadata": {"HTTPStatusCode": 412},
                },
                "PutObject",
            )
        body = arguments["Body"]
        self.uploaded_body = body.read()  # type: ignore[union-attr]
        return {"ETag": '"test-etag"'}


class UploadToS3Tests(unittest.TestCase):
    def test_parse_s3_uri_returns_bucket_and_key(self) -> None:
        self.assertEqual(
            parse_s3_uri("s3://example-bucket/processed/data%20file.parquet"),
            ("example-bucket", "processed/data file.parquet"),
        )

    def test_parse_s3_uri_rejects_invalid_uris(self) -> None:
        for uri in ("s3://example-bucket", "https://example-bucket/key"):
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                parse_s3_uri(uri)

    def test_uploads_file_with_conditional_write_and_content_type(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source_path = Path(temporary_directory) / "result.parquet"
            source_path.write_bytes(b"test parquet content")
            fake_s3 = FakeS3Client()

            result = upload_file_to_s3(
                source_path,
                "s3://example-bucket/processed/result.parquet",
                s3_client=fake_s3,  # type: ignore[arg-type]
            )

        self.assertEqual(result, "s3://example-bucket/processed/result.parquet")
        self.assertEqual(fake_s3.upload_arguments["Bucket"], "example-bucket")
        self.assertEqual(fake_s3.upload_arguments["Key"], "processed/result.parquet")
        self.assertEqual(fake_s3.upload_arguments["IfNoneMatch"], "*")
        self.assertEqual(
            fake_s3.upload_arguments["ContentType"],
            "application/vnd.apache.parquet",
        )
        self.assertEqual(fake_s3.uploaded_body, b"test parquet content")

    def test_upload_rejects_existing_object(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source_path = Path(temporary_directory) / "result.parquet"
            source_path.write_bytes(b"test parquet content")

            with self.assertRaisesRegex(FileExistsError, "Refusing to overwrite"):
                upload_file_to_s3(
                    source_path,
                    "s3://example-bucket/processed/result.parquet",
                    s3_client=FakeS3Client(object_exists=True),  # type: ignore[arg-type]
                )

    def test_upload_requires_an_existing_local_file(self) -> None:
        with self.assertRaises(FileNotFoundError):
            upload_file_to_s3(
                Path("missing.parquet"),
                "s3://example-bucket/processed/result.parquet",
                s3_client=FakeS3Client(),  # type: ignore[arg-type]
            )


if __name__ == "__main__":
    unittest.main()
