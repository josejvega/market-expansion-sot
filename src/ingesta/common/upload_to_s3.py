"""Upload local ingestion outputs to Amazon S3."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterable

import boto3
from dotenv import load_dotenv

LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def upload_files_to_s3(
    file_paths: Iterable[Path],
    bucket_name: str | None = None,
    prefix: str = "raw",
    region_name: str | None = None,
) -> list[str]:
    """Upload files using local .env settings or boto3's default credential chain."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    bucket_name = bucket_name or os.getenv("S3_BUCKET")
    region_name = region_name or os.getenv("AWS_DEFAULT_REGION")
    if not bucket_name or not bucket_name.strip():
        raise ValueError("An S3 bucket name is required.")

    client_options = {"region_name": region_name} if region_name else {}
    client = boto3.client("s3", **client_options)
    normalized_prefix = prefix.strip("/")
    uploaded_uris = []

    for file_path in file_paths:
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"File to upload does not exist: {path}")
        object_key = f"{normalized_prefix}/{path.name}" if normalized_prefix else path.name
        client.upload_file(str(path), bucket_name, object_key)
        uri = f"s3://{bucket_name}/{object_key}"
        uploaded_uris.append(uri)
        LOGGER.info("Uploaded %s to S3.", uri)

    return uploaded_uris
