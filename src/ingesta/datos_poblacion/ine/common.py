"""Shared download and year-selection helpers for INE tables."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import pandas as pd
import requests

from ...common.ingestion import retry_delay, utc_now

LOGGER = logging.getLogger(__name__)
INE_TABLE_URL = "https://www.ine.es/jaxiT3/files/t/es/csv_bdsc/{table_id}.csv"
DOWNLOAD_ATTEMPTS = 3
ANDALUSIA_PROVINCES = {
    "04": "Almería",
    "11": "Cádiz",
    "14": "Córdoba",
    "18": "Granada",
    "21": "Huelva",
    "23": "Jaén",
    "29": "Málaga",
    "41": "Sevilla",
}


def download_ine_table(
    session: requests.Session,
    table_id: int,
    destination: Path,
) -> str:
    """Stream an INE CSV with retries and return its download timestamp."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination.with_suffix(destination.suffix + ".part")
    url = INE_TABLE_URL.format(table_id=table_id)
    try:
        for attempt in range(DOWNLOAD_ATTEMPTS):
            response = None
            try:
                with session.get(url, stream=True, timeout=(20, 300)) as response:
                    response.raise_for_status()
                    with temporary_path.open("wb") as output_file:
                        for chunk in response.iter_content(chunk_size=1024 * 1024):
                            if chunk:
                                output_file.write(chunk)
                temporary_path.replace(destination)
                break
            except requests.exceptions.SSLError:
                raise
            except requests.RequestException as error:
                status_code = (
                    response.status_code if response is not None else None
                )
                if (
                    status_code is not None
                    and 400 <= status_code < 500
                    and status_code not in {408, 429}
                ):
                    raise
                LOGGER.warning(
                    "INE table %s download failed (attempt %s/%s): %s",
                    table_id,
                    attempt + 1,
                    DOWNLOAD_ATTEMPTS,
                    error,
                )
                if attempt == DOWNLOAD_ATTEMPTS - 1:
                    raise RuntimeError(
                        f"INE table {table_id} download failed after "
                        f"{DOWNLOAD_ATTEMPTS} attempts."
                    ) from error
                delay = retry_delay(response, attempt)
                LOGGER.info(
                    "Retrying INE table %s download in %.0f seconds.",
                    table_id,
                    delay,
                )
                temporary_path.unlink(missing_ok=True)
                time.sleep(delay)
    finally:
        temporary_path.unlink(missing_ok=True)

    downloaded_at_utc = utc_now()
    LOGGER.info("Downloaded INE table %s.", table_id)
    return downloaded_at_utc


def latest_years(source_path: Path, number_of_years: int) -> list[int]:
    if number_of_years < 1:
        raise ValueError("The number of years must be positive.")

    available_years: set[int] = set()
    for chunk in pd.read_csv(
        source_path,
        sep=";",
        usecols=["Periodo"],
        dtype=str,
        chunksize=200_000,
        encoding="utf-8-sig",
    ):
        periods = pd.to_numeric(chunk["Periodo"], errors="coerce").dropna()
        available_years.update(periods.astype(int).tolist())

    selected_years = sorted(available_years, reverse=True)[:number_of_years]
    if len(selected_years) != number_of_years:
        raise ValueError(
            f"The INE table has fewer than {number_of_years} published years."
        )
    return selected_years
