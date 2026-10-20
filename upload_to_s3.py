"""Upload local files to S3 without overwriting existing objects."""

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from urllib.parse import unquote, urlsplit

import boto3
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import ClientError

LOGGER = logging.getLogger(__name__)
CONTENT_TYPES = {
    ".gpkg": "application/geopackage+sqlite3",
    ".parquet": "application/vnd.apache.parquet",
}


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
    """Upload a local file to S3, refusing to overwrite an existing object."""
    source_path = Path(file_path)
    if not source_path.is_file():
        raise FileNotFoundError(f"File to upload does not exist: {source_path}")

    bucket, key = parse_s3_uri(destination_s3_uri)
    media_type = (
        content_type
        or CONTENT_TYPES.get(source_path.suffix.lower())
        or mimetypes.guess_type(source_path.name)[0]
    )
    client = s3_client
    if client is None:
        client = boto3.client(
            "s3",
            config=Config(
                connect_timeout=10,
                read_timeout=120,
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )

    arguments: dict[str, object] = {
        "Bucket": bucket,
        "Key": key,
        "IfNoneMatch": "*",
    }
    if media_type is not None:
        arguments["ContentType"] = media_type

    try:
        with source_path.open("rb") as file_object:
            client.put_object(Body=file_object, **arguments)
    except ClientError as error:
        error_code = error.response.get("Error", {}).get("Code")
        status_code = error.response.get("ResponseMetadata", {}).get(
            "HTTPStatusCode"
        )
        if error_code == "PreconditionFailed" or status_code == 412:
            raise FileExistsError(
                f"Refusing to overwrite existing S3 object: {destination_s3_uri}"
            ) from error
        raise

    LOGGER.info("Uploaded %s to %s.", source_path, destination_s3_uri)
    return destination_s3_uri
