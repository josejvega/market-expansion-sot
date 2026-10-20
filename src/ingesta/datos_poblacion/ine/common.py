"""Shared download and year-selection helpers for INE tables."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import requests

from ...common.ingestion import utc_now

LOGGER = logging.getLogger(__name__)
INE_TABLE_URL = "https://www.ine.es/jaxiT3/files/t/es/csv_bdsc/{table_id}.csv"
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
    """Stream a source CSV to a temporary path and return its download timestamp."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination.with_suffix(destination.suffix + ".part")
    url = INE_TABLE_URL.format(table_id=table_id)
    try:
        with session.get(url, stream=True, timeout=(15, 120)) as response:
            response.raise_for_status()
            with temporary_path.open("wb") as output_file:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        output_file.write(chunk)
        temporary_path.replace(destination)
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
