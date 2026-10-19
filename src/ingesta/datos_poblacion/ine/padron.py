"""Download municipal population data for Andalusia from the INE."""

from __future__ import annotations

import logging
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
import requests

from ...common.ingestion import RAW_DIR
from .common import ANDALUSIA_PROVINCES, download_ine_table, latest_years

LOGGER = logging.getLogger(__name__)
TABLE_ID = 68542
OUTPUT_NAME = "population_andalusia.csv"
SOURCE_COLUMNS = [
    "Provincias",
    "Municipios",
    "Sexo",
    "Edad",
    "Periodo",
    "Total",
]


def download_andalusia_population_by_municipality_from_ine(
    number_of_years: int = 5,
    output_dir: Path = RAW_DIR,
) -> Path:
    """Save Andalusian population by municipality and year."""
    output_dir = Path(output_dir)
    output_path = Path(output_dir) / OUTPUT_NAME
    output_dir.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(prefix="ine-population-", dir=output_dir) as temp_dir:
        source_path = Path(temp_dir) / "source.csv"
        staging_path = Path(temp_dir) / OUTPUT_NAME
        # Descargamos el CSV original a un temporal; solo se conservara el resultado filtrado.
        with requests.Session() as session:
            downloaded_at_utc = download_ine_table(session, TABLE_ID, source_path)

        # Consultamos los periodos disponibles y limitamos el Bronze a los mas recientes.
        years = latest_years(source_path, number_of_years)
        selected_years = {str(year) for year in years}
        rows_written = 0

        # Procesamos por bloques para no cargar la tabla completa en memoria.
        for chunk in pd.read_csv(
            source_path,
            sep=";",
            usecols=SOURCE_COLUMNS,
            dtype=str,
            keep_default_na=False,
            chunksize=200_000,
            encoding="utf-8-sig",
        ):
            province_codes = chunk["Municipios"].str[:2]
            # El unico filtro de contenido es provincia andaluza y periodo; el resto queda original.
            selected = chunk.loc[
                province_codes.isin(ANDALUSIA_PROVINCES)
                & chunk["Periodo"].isin(selected_years)
            ].copy()
            if selected.empty:
                continue

            # Registramos procedencia y momento de descarga en cada fila seleccionada.
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
            raise ValueError("The INE table contains no population data for Andalusia.")
        # Publicamos el CSV solo cuando la descarga y el filtrado han terminado bien.
        staging_path.replace(output_path)

    LOGGER.info(
        "Saved %s Andalusian population rows for years %s to %s.",
        rows_written,
        years,
        output_path,
    )
    return output_path
