"""Download municipal mean net income data for Andalusia from the INE."""

from __future__ import annotations

import logging
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
import requests

from ...common.ingestion import RAW_DIR
from .common import ANDALUSIA_PROVINCES, download_ine_table, latest_years

LOGGER = logging.getLogger(__name__)
TABLE_ID = 30824
OUTPUT_NAME = "income_andalusia.csv"
INCOME_INDICATOR = "Renta neta media por persona"
SOURCE_COLUMNS = [
    "Municipios",
    "Distritos",
    "Secciones",
    "Indicadores de renta media",
    "Periodo",
    "Total",
]


def download_andalusia_income_by_municipality_from_ine(
    number_of_years: int = 1,
    output_dir: Path = RAW_DIR,
) -> Path:
    """Save municipal mean net income for the latest published INE year(s)."""
    output_dir = Path(output_dir)
    output_path = Path(output_dir) / OUTPUT_NAME
    output_dir.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(prefix="ine-income-", dir=output_dir) as temp_dir:
        source_path = Path(temp_dir) / "source.csv"
        staging_path = Path(temp_dir) / OUTPUT_NAME
        # Descargamos el CSV original en un temporal para no guardar la tabla nacional.
        with requests.Session() as session:
            downloaded_at_utc = download_ine_table(session, TABLE_ID, source_path)

        # Seleccionamos los periodos mas recientes solicitados por el llamador.
        years = latest_years(source_path, number_of_years)
        selected_years = {str(year) for year in years}
        rows_written = 0

        # Leemos por bloques para limitar el uso de memoria.
        for chunk in pd.read_csv(
            source_path,
            sep=";",
            usecols=SOURCE_COLUMNS,
            dtype=str,
            keep_default_na=False,
            chunksize=100_000,
            encoding="utf-8-sig",
        ):
            province_codes = chunk["Municipios"].str[:2]
            # Conservamos solo Andalucía, filas municipales y el indicador elegido, sin transformar sus valores.
            selected = chunk.loc[
                province_codes.isin(ANDALUSIA_PROVINCES)
                & chunk["Distritos"].eq("")
                & chunk["Secciones"].eq("")
                & chunk["Indicadores de renta media"].eq(INCOME_INDICATOR)
                & chunk["Periodo"].isin(selected_years)
            ].copy()
            if selected.empty:
                continue

            # Anotamos la fuente y el instante UTC de la descarga en cada fila.
            selected["source"] = "INE"
            selected["downloaded_at_utc"] = downloaded_at_utc
            selected.to_csv(
                staging_path,
                index=False,
                mode="a",
                header=rows_written == 0,
                encoding="utf-8",
            )
            rows_written += len(selected)

        if rows_written == 0:
            raise ValueError("The INE table contains no matching Andalusian income data.")
        # Reemplazamos el destino al final para no dejar un CSV parcial ante un fallo.
        staging_path.replace(output_path)

    LOGGER.info(
        "Saved %s Andalusian income rows for years %s to %s.",
        rows_written,
        years,
        output_path,
    )
    return output_path
