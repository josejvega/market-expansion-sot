"""Shared HTTP, JSON, CSV, and timestamp helpers for ingestion modules."""

from __future__ import annotations

import json
import logging
import shutil
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Literal

import pandas as pd
import requests

LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
RAW_DIR = PROJECT_ROOT / "data" / "raw"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(path)


def save_response(payload: dict[str, Any], path: Path) -> None:
    if path.exists():
        history_dir = path.parent / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        shutil.copy2(path, history_dir / f"{path.stem}_{timestamp}{path.suffix}")
    save_json(payload, path)


def save_csv(dataframe: pd.DataFrame, path: Path, separator: str = ",") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    dataframe.to_csv(temporary_path, index=False, sep=separator, encoding="utf-8")
    temporary_path.replace(path)


def retry_delay(response: requests.Response | None, attempt: int) -> float:
    delay = float(30 * 2**attempt)
    retry_after = response.headers.get("Retry-After") if response is not None else None
    if not retry_after:
        return delay
    try:
        if retry_after.isdigit():
            return max(delay, float(retry_after))
        retry_at = parsedate_to_datetime(retry_after)
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(delay, (retry_at - datetime.now(timezone.utc)).total_seconds())
    except (ValueError, TypeError, OverflowError):
        LOGGER.warning(
            "Invalid Retry-After value %r; using the exponential backoff.",
            retry_after,
        )
        return delay


def request_json(
    session: requests.Session,
    url: str,
    params: dict[str, Any],
    validator: Callable[[dict[str, Any]], Any],
    *,
    source: str,
    method: Literal["GET", "POST"] = "GET",
    timeout: tuple[int, int] = (20, 300),
    attempts: int = 3,
    fallback_urls: tuple[str, ...] = (),
) -> dict[str, Any]:
    if attempts < 1:
        raise ValueError("The number of request attempts must be positive.")
    urls = (url, *fallback_urls)
    for attempt in range(attempts):
        response = None
        request_url = urls[min(attempt, len(urls) - 1)]
        try:
            if method == "POST":
                response = session.post(request_url, data=params, timeout=timeout)
            else:
                response = session.get(request_url, params=params, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
            validator(payload)
            return payload
        except requests.exceptions.SSLError:
            raise
        except (requests.RequestException, ValueError) as error:
            LOGGER.warning(
                "%s request to %s failed (attempt %s/%s): %s",
                source,
                request_url,
                attempt + 1,
                attempts,
                error,
            )
            if (
                response is not None
                and 400 <= response.status_code < 500
                and response.status_code not in {408, 429}
            ):
                raise
            if attempt == attempts - 1:
                raise RuntimeError(
                    f"The {source} ingestion failed; run it again to resume."
                ) from error
            delay = retry_delay(response, attempt)
            LOGGER.info("Retrying in %.0f seconds.", delay)
            time.sleep(delay)
    raise RuntimeError("Request retry loop ended unexpectedly.")
