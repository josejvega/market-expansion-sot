"""Shared storage settings and readers for local and S3-backed datasets."""

from __future__ import annotations

import io
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import boto3
import pandas as pd
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv

from .upload_to_s3 import PROJECT_ROOT

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class StorageSettings:
    save_locally: bool
    save_s3: bool
    bucket_name: str | None
    region_name: str | None


def _read_bool_setting(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise ValueError(f"{name} must be set to true or false, got {value!r}.")


def get_storage_settings() -> StorageSettings:
    """Load output flags and AWS location from the project .env or environment."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    return StorageSettings(
        save_locally=_read_bool_setting("SAVE_LOCALLY", True),
        save_s3=_read_bool_setting("SAVE_S3", True),
        bucket_name=os.getenv("S3_BUCKET") or None,
        region_name=os.getenv("AWS_DEFAULT_REGION") or None,
    )


def s3_uri_for(filename: str, prefix: str) -> str | None:
    """Build an S3 URI from the configured bucket, if one is available."""
    bucket = get_storage_settings().bucket_name
    if not bucket or not bucket.strip():
        return None
    normalized_prefix = prefix.strip("/")
    key = f"{normalized_prefix}/{filename}" if normalized_prefix else filename
    return f"s3://{bucket}/{key}"


def read_csv_dataset(
    local_path: Path | str,
    s3_uri: str | None = None,
    **read_csv_options: Any,
) -> pd.DataFrame:
    """Prefer the S3 CSV and fall back to its local copy when S3 is unavailable."""
    if isinstance(local_path, str) and local_path.startswith("s3://"):
        s3_uri = local_path
        local_path = Path(local_path)
    local_path = Path(local_path)
    settings = get_storage_settings()
    if not s3_uri:
        if not local_path.is_file():
            raise FileNotFoundError(f"Dataset is not available locally: {local_path}")
        return pd.read_csv(local_path, **read_csv_options)

    if not settings.bucket_name or not s3_uri.startswith(
        f"s3://{settings.bucket_name}/"
    ):
        raise ValueError("The S3 dataset URI does not match the configured bucket.")
    bucket_and_key = s3_uri[len("s3://") :].split("/", 1)
    if len(bucket_and_key) != 2 or not bucket_and_key[1]:
        raise ValueError(f"Expected an S3 object URI, got {s3_uri!r}")

    client_options = (
        {"region_name": settings.region_name} if settings.region_name else {}
    )
    try:
        response = boto3.client("s3", **client_options).get_object(
            Bucket=bucket_and_key[0],
            Key=bucket_and_key[1],
        )
        with response["Body"] as body:
            csv_contents = body.read()
    except (BotoCoreError, ClientError) as error:
        if not local_path.is_file():
            raise RuntimeError(
                f"Could not read {s3_uri} from S3 and no local fallback exists "
                f"at {local_path}."
            ) from error
        LOGGER.warning(
            "Could not read %s from S3; falling back to local file %s: %s",
            s3_uri,
            local_path,
            error,
        )
        return pd.read_csv(local_path, **read_csv_options)

    return pd.read_csv(io.BytesIO(csv_contents), **read_csv_options)
