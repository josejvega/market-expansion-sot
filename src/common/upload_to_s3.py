"""Upload local files to S3, replacing objects at the destination URI."""

from __future__ import annotations

import logging
import mimetypes
import os
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urlsplit

import boto3
from boto3.s3.transfer import S3UploadFailedError
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv

LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTENT_TYPES = {
    ".gpkg": "application/geopackage+sqlite3",
    ".parquet": "application/vnd.apache.parquet",
    ".csv": "text/csv",
}


def _create_s3_client(region_name: str | None = None) -> BaseClient:
    client_options: dict[str, object] = {
        "config": Config(
            connect_timeout=10,
            read_timeout=120,
            retries={"max_attempts": 3, "mode": "standard"},
        )
    }
    if region_name:
        client_options["region_name"] = region_name
    return boto3.client("s3", **client_options)


def parse_s3_uri(uri: str) -> tuple[str, str]:
    """Return the bucket and object key from a complete S3 URI."""
    parsed = urlsplit(uri)
    key = unquote(parsed.path.lstrip("/"))
    if parsed.scheme != "s3" or not parsed.netloc or not key:
        raise ValueError(f"Expected an S3 object URI, got: {uri!r}")
    if parsed.query or parsed.fragment:
        raise ValueError("S3 object URIs must not contain a query or fragment.")
    return parsed.netloc, key


def upload_file_to_s3(
    file_path: str | Path,
    destination_s3_uri: str,
    content_type: str | None = None,
    s3_client: BaseClient | None = None,
) -> str:
    """Upload any local file to S3, replacing the destination object if present."""
    source_path = Path(file_path)
    if not source_path.is_file():
        raise FileNotFoundError(f"File to upload does not exist: {source_path}")

    bucket, key = parse_s3_uri(destination_s3_uri)
    media_type = (
        content_type
        or CONTENT_TYPES.get(source_path.suffix.lower())
        or mimetypes.guess_type(source_path.name)[0]
    )
    client = s3_client or _create_s3_client()

    extra_args: dict[str, str] = {}
    if media_type is not None:
        extra_args["ContentType"] = media_type

    if extra_args:
        client.upload_file(
            str(source_path),
            bucket,
            key,
            ExtraArgs=extra_args,
        )
    else:
        client.upload_file(str(source_path), bucket, key)

    LOGGER.info("Uploaded %s to %s.", source_path, destination_s3_uri)
    return destination_s3_uri


def upload_files_to_s3(
    file_paths: Iterable[str | Path],
    bucket_name: str | None = None,
    prefix: str = "raw",
    region_name: str | None = None,
) -> list[str]:
    """Upload multiple local files to a prefix; raise if configuration or upload fails."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    resolved_bucket = bucket_name or os.getenv("S3_BUCKET")
    region_name = region_name or os.getenv("AWS_DEFAULT_REGION")
    if not resolved_bucket or not resolved_bucket.strip():
        raise ValueError("An S3 bucket name is required.")

    source_paths = [Path(file_path) for file_path in file_paths]
    for source_path in source_paths:
        if not source_path.is_file():
            raise FileNotFoundError(f"File to upload does not exist: {source_path}")

    normalized_prefix = prefix.strip("/")
    client = _create_s3_client(region_name)
    uploaded_uris = []
    for source_path in source_paths:
        object_key = (
            f"{normalized_prefix}/{source_path.name}"
            if normalized_prefix
            else source_path.name
        )
        destination_uri = f"s3://{resolved_bucket}/{object_key}"
        try:
            uploaded_uris.append(
                upload_file_to_s3(
                    source_path,
                    destination_uri,
                    s3_client=client,
                )
            )
        except (BotoCoreError, ClientError, S3UploadFailedError):
            LOGGER.exception("Failed to upload %s to %s.", source_path, destination_uri)
            raise
    return uploaded_uris
