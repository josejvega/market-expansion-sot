"""Cleaning wrappers that persist Silver outputs locally, to S3, or both."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, TypeVar

import geopandas as gpd
import pandas as pd

from src.common.storage import get_storage_settings
from src.common.upload_to_s3 import upload_files_to_s3
from src.procesado.common.paths import (
    GYMS_FAILED_PATH,
    GYMS_SILVER_PATH,
    INCOME_FAILED_PATH,
    INCOME_SILVER_PATH,
    MUNICIPALITY_BOUNDARIES_SILVER_PATH,
    POPULATION_FAILED_PATH,
    POPULATION_SILVER_PATH,
)
from src.procesado.limpiar_gimnasios import clean_gyms
from src.procesado.limpiar_limites_municipales import (
    clean_municipality_boundaries,
    cnig_csv_to_geodataframe,
)
from src.procesado.limpiar_poblacion import clean_population
from src.procesado.limpiar_renta import clean_income

Cleaner = TypeVar("Cleaner", bound=Callable[..., pd.DataFrame])
SILVER_PREFIX = "processed/silver"
FAILED_PREFIX = "processed/silver/failed"


def _run_cleaner(
    source: pd.DataFrame,
    cleaner: Cleaner,
    silver_path: Path,
    failed_path: Path,
) -> pd.DataFrame:
    settings = get_storage_settings()

    def execute(temporary_dir: Path | None) -> pd.DataFrame:
        output_silver = silver_path if settings.save_locally else None
        output_failed = failed_path if settings.save_locally else None
        if temporary_dir is not None:
            output_silver = temporary_dir / silver_path.name
            output_failed = temporary_dir / failed_path.name
        elif settings.save_s3 and not settings.save_locally:
            raise RuntimeError("Temporary output storage is required for S3 uploads.")

        cleaned = cleaner(source, failed_output_path=output_failed)
        if output_silver is not None:
            output_silver.parent.mkdir(parents=True, exist_ok=True)
            cleaned.to_parquet(output_silver, index=False)
            if settings.save_s3:
                upload_files_to_s3(
                    [output_silver],
                    prefix=SILVER_PREFIX,
                    bucket_name=settings.bucket_name,
                    region_name=settings.region_name,
                )
        if output_failed is not None and settings.save_s3:
            upload_files_to_s3(
                [output_failed],
                prefix=FAILED_PREFIX,
                bucket_name=settings.bucket_name,
                region_name=settings.region_name,
            )
        return cleaned

    if settings.save_locally:
        return execute(None)
    if settings.save_s3:
        with TemporaryDirectory(prefix="market-expansion-silver-") as directory:
            return execute(Path(directory))
    return execute(None)


def clean_and_upload_population(population: pd.DataFrame) -> pd.DataFrame:
    return _run_cleaner(
        population,
        clean_population,
        POPULATION_SILVER_PATH,
        POPULATION_FAILED_PATH,
    )


def clean_and_upload_income(income: pd.DataFrame) -> pd.DataFrame:
    return _run_cleaner(
        income,
        clean_income,
        INCOME_SILVER_PATH,
        INCOME_FAILED_PATH,
    )


def clean_and_upload_gyms(gyms: pd.DataFrame) -> gpd.GeoDataFrame:
    return _run_cleaner(
        gyms,
        clean_gyms,
        GYMS_SILVER_PATH,
        GYMS_FAILED_PATH,
    )


def clean_and_upload_municipality_boundaries(
    raw_boundaries: pd.DataFrame,
) -> gpd.GeoDataFrame:
    settings = get_storage_settings()
    source = cnig_csv_to_geodataframe(raw_boundaries)

    def persist(temporary_dir: Path | None) -> gpd.GeoDataFrame:
        cleaned = clean_municipality_boundaries(source)
        output_path = (
            MUNICIPALITY_BOUNDARIES_SILVER_PATH
            if settings.save_locally
            else temporary_dir / MUNICIPALITY_BOUNDARIES_SILVER_PATH.name
            if temporary_dir is not None
            else None
        )
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            cleaned.to_parquet(output_path, index=False, compression="snappy")
            if settings.save_s3:
                upload_files_to_s3(
                    [output_path],
                    prefix=SILVER_PREFIX,
                    bucket_name=settings.bucket_name,
                    region_name=settings.region_name,
                )
        return cleaned

    if settings.save_locally:
        return persist(None)
    if settings.save_s3:
        with TemporaryDirectory(prefix="market-expansion-silver-") as directory:
            return persist(Path(directory))
    return persist(None)
