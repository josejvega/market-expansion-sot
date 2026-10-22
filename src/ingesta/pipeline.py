"""Ingestion wrappers that persist raw datasets according to storage settings."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, TypeVar

from src.common.storage import get_storage_settings
from src.common.upload_to_s3 import upload_files_to_s3
from src.ingesta.common.ingestion import RAW_DIR
from src.ingesta.datos_poblacion.ine.padron import (
    download_andalusia_population_by_municipality_from_ine,
)
from src.ingesta.datos_poblacion.ine.renta import (
    download_andalusia_income_by_municipality_from_ine,
)
from src.ingesta.gimnasios.osm import download_andalusia_gyms_from_osm
from src.ingesta.limites_municipios.cnig import (
    download_andalusia_municipality_boundaries_from_cnig,
)

Download = TypeVar("Download", bound=Callable[..., Path])
RAW_PREFIX = "raw/data"


def _run_download(
    download: Download,
    **kwargs: object,
) -> Path | str | None:
    settings = get_storage_settings()
    output_dir = Path(kwargs.pop("output_dir", RAW_DIR))

    def execute(target_dir: Path) -> Path | str | None:
        result_path = Path(download(output_dir=target_dir, **kwargs))
        if settings.save_s3:
            uploaded_uris = upload_files_to_s3(
                [result_path],
                prefix=RAW_PREFIX,
                bucket_name=settings.bucket_name,
                region_name=settings.region_name,
            )
            if not settings.save_locally:
                return uploaded_uris[0] if uploaded_uris else None
        return result_path if settings.save_locally else None

    if settings.save_locally:
        return execute(output_dir)
    with TemporaryDirectory(prefix="market-expansion-raw-") as temporary_directory:
        result = execute(Path(temporary_directory))
        return result


def download_and_upload_population(
    number_of_years: int = 5,
) -> Path | str | None:
    return _run_download(
        download_andalusia_population_by_municipality_from_ine,
        number_of_years=number_of_years,
    )


def download_and_upload_income(
    number_of_years: int = 1,
) -> Path | str | None:
    return _run_download(
        download_andalusia_income_by_municipality_from_ine,
        number_of_years=number_of_years,
    )


def download_and_upload_gyms(refresh: bool = False) -> Path | str | None:
    return _run_download(
        download_andalusia_gyms_from_osm,
        refresh=refresh,
    )


def download_and_upload_municipality_boundaries(
    refresh: bool = False,
) -> Path | str | None:
    return _run_download(
        download_andalusia_municipality_boundaries_from_cnig,
        refresh=refresh,
    )
