"""Upload local ingestion outputs to Amazon S3."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterable

import boto3
from boto3.s3.transfer import S3UploadFailedError
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv

LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def upload_files_to_s3(
    file_paths: Iterable[Path],
    bucket_name: str | None = None,
    prefix: str = "raw",
    region_name: str | None = None,
) -> list[str]:
    """Best-effort upload; log S3 failures and return only successfully uploaded URIs."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    bucket_name = bucket_name or os.getenv("S3_BUCKET")
    region_name = region_name or os.getenv("AWS_DEFAULT_REGION")

    paths = [Path(file_path) for file_path in file_paths]
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"File to upload does not exist: {path}")

    if not bucket_name or not bucket_name.strip():
        LOGGER.warning(
            "S3_BUCKET is not configured; local files were kept but not uploaded."
        )
        return []

    normalized_prefix = prefix.strip("/")
    uploaded_uris = []

    client_options = {"region_name": region_name} if region_name else {}
    try:
        client = boto3.client("s3", **client_options)
    except (BotoCoreError, ClientError) as error:
        LOGGER.warning(
            "Could not initialize S3 client; local files were kept but not uploaded: %s",
            error,
        )
        return uploaded_uris

    for path in paths:
        object_key = f"{normalized_prefix}/{path.name}" if normalized_prefix else path.name
        uri = f"s3://{bucket_name}/{object_key}"
        try:
            client.upload_file(str(path), bucket_name, object_key)
        except (BotoCoreError, ClientError, S3UploadFailedError) as error:
            LOGGER.warning(
                "Could not upload %s to S3; the local file was kept: %s",
                path,
                error,
            )
            continue
        uploaded_uris.append(uri)
        LOGGER.info("Uploaded %s to S3.", uri)

    return uploaded_uris
