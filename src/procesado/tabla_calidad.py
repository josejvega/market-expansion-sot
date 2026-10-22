"""Build and persist source-quality and cross-coverage metrics."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from src.common.storage import get_storage_settings
from src.common.upload_to_s3 import upload_files_to_s3
from src.procesado.common.paths import QUALITY_TABLE_PATH

QUALITY_PREFIX = "processed/quality"
INCOME_INDICATOR = "Renta neta media por persona"
QUALITY_COLUMNS = [
    "source",
    "records",
    "records_after_cleaning",
    "key_fields",
    "records_with_null_key",
    "pct_records_with_null_key",
    "duplicate_records",
    "candidate_municipalities",
    "cleaned_municipalities",
    "municipality_retention_pct",
    "records_eligible_for_cross",
    "records_crossed",
    "records_not_crossed",
    "cross_pct",
    "decision_adopted",
]


def _require_columns(
    table: pd.DataFrame,
    source_name: str,
    required_columns: set[str],
) -> None:
    missing = sorted(required_columns.difference(table.columns))
    if missing:
        raise ValueError(f"Missing required {source_name} columns: {missing}")


def _normalize_key_values(table: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    normalized = table.loc[:, columns].copy()
    for column in columns:
        values = normalized[column].astype("string").str.strip()
        normalized[column] = values.mask(values.eq(""), pd.NA)
    return normalized


def _raw_quality_stats(
    raw: pd.DataFrame,
    source_name: str,
    key_fields: list[str],
    duplicate_key_fields: list[str],
) -> tuple[int, float | None, int]:
    _require_columns(raw, source_name, set(key_fields + duplicate_key_fields))
    key_values = _normalize_key_values(raw, key_fields)
    rows_with_null_key = int(key_values.isna().any(axis=1).sum())
    null_key_pct = rows_with_null_key / len(raw) * 100 if len(raw) else None

    duplicate_values = _normalize_key_values(raw, duplicate_key_fields)
    duplicate_records = int(
        duplicate_values.duplicated(keep="first").sum()
    )
    return rows_with_null_key, null_key_pct, duplicate_records


def _municipality_codes_from_cleaned(table: pd.DataFrame) -> set[str]:
    _require_columns(table, "cleaned source", {"municipality_code"})
    return set(
        table["municipality_code"]
        .dropna()
        .astype("string")
        .str.strip()
        .loc[lambda values: values.ne("")]
    )


def _candidate_codes_from_values(values: pd.Series, pattern: str) -> set[str]:
    codes = values.astype("string").str.extract(pattern, expand=False).dropna()
    return set(codes.astype("string").str.strip())


def _population_candidate_codes(population_bronze: pd.DataFrame) -> set[str]:
    _require_columns(population_bronze, "population Bronze", {"Municipios"})
    return _candidate_codes_from_values(
        population_bronze["Municipios"],
        r"^\s*(\d{5})\s+",
    )


def _income_candidate_codes(income_bronze: pd.DataFrame) -> set[str]:
    _require_columns(
        income_bronze,
        "income Bronze",
        {
            "Municipios",
            "Distritos",
            "Secciones",
            "Indicadores de renta media",
        },
    )
    indicator = (
        income_bronze["Indicadores de renta media"]
        .astype("string")
        .str.strip()
    )
    districts = income_bronze["Distritos"].astype("string").str.strip()
    sections = income_bronze["Secciones"].astype("string").str.strip()
    municipality_rows = income_bronze.loc[
        indicator.eq(INCOME_INDICATOR)
        & districts.fillna("").eq("")
        & sections.fillna("").eq("")
    ]
    return _candidate_codes_from_values(
        municipality_rows["Municipios"],
        r"^\s*(\d{5})\s+",
    )


def _cnig_candidate_codes(cnig_bronze: pd.DataFrame) -> set[str]:
    _require_columns(cnig_bronze, "CNIG Bronze", {"nationalCode"})
    return _candidate_codes_from_values(
        cnig_bronze["nationalCode"],
        r"(\d{5})$",
    )


def _cross_counts(
    records: pd.DataFrame,
    gold_municipality_codes: set[str],
    source_name: str,
) -> tuple[int, int, int, float | None]:
    _require_columns(records, source_name, {"municipality_code"})
    codes = records["municipality_code"].astype("string").str.strip()
    crossed_mask = codes.isin(gold_municipality_codes)
    total_records = len(records)
    crossed_records = int(crossed_mask.sum())
    not_crossed_records = total_records - crossed_records
    cross_pct = crossed_records / total_records * 100 if total_records else None
    return total_records, crossed_records, not_crossed_records, cross_pct


def _make_source_row(
    *,
    source: str,
    raw: pd.DataFrame,
    cleaned: pd.DataFrame,
    key_fields: list[str],
    duplicate_key_fields: list[str],
    candidate_municipalities: set[str] | None,
    cross_records: pd.DataFrame,
    gold_municipality_codes: set[str],
    decision_adopted: str,
) -> dict[str, object]:
    null_rows, null_pct, duplicate_records = _raw_quality_stats(
        raw,
        source,
        key_fields,
        duplicate_key_fields,
    )
    cross_total, crossed, not_crossed, cross_pct = _cross_counts(
        cross_records,
        gold_municipality_codes,
        source,
    )
    candidate_count: int | None = None
    cleaned_municipality_count: int | None = None
    retention_pct: float | None = None
    if candidate_municipalities is not None:
        cleaned_municipality_codes = _municipality_codes_from_cleaned(cleaned)
        candidate_count = len(candidate_municipalities)
        cleaned_municipality_count = len(cleaned_municipality_codes)
        retention_pct = (
            len(candidate_municipalities.intersection(cleaned_municipality_codes))
            / candidate_count
            * 100
            if candidate_count
            else None
        )
        excluded_candidates = len(
            candidate_municipalities.difference(cleaned_municipality_codes)
        )
        if excluded_candidates:
            decision_adopted = (
                f"{decision_adopted} {excluded_candidates} códigos municipales "
                "candidatos no superaron la limpieza y se excluyeron de Silver."
            )

    if not_crossed:
        decision_adopted = (
            f"{decision_adopted} {not_crossed} registros limpios no cruzaron con "
            "Gold y se excluyeron de sus agregados."
        )

    return {
        "source": source,
        "records": len(raw),
        "records_after_cleaning": len(cleaned),
        "key_fields": ", ".join(key_fields),
        "records_with_null_key": null_rows,
        "pct_records_with_null_key": null_pct,
        "duplicate_records": duplicate_records,
        "candidate_municipalities": candidate_count,
        "cleaned_municipalities": cleaned_municipality_count,
        "municipality_retention_pct": retention_pct,
        "records_eligible_for_cross": cross_total,
        "records_crossed": crossed,
        "records_not_crossed": not_crossed,
        "cross_pct": cross_pct,
        "decision_adopted": decision_adopted,
    }


def create_quality_table(
    population_bronze: pd.DataFrame,
    population_cleaned: pd.DataFrame,
    income_bronze: pd.DataFrame,
    income_cleaned: pd.DataFrame,
    gyms_bronze: pd.DataFrame,
    gyms_cleaned: pd.DataFrame,
    cnig_bronze: pd.DataFrame,
    cnig_cleaned: pd.DataFrame,
    gyms_with_municipality: pd.DataFrame,
    gold_municipalities: pd.DataFrame,
) -> pd.DataFrame:
    """Report raw quality and cleaned-record coverage into Gold, one row per source."""
    gold_municipality_codes = _municipality_codes_from_cleaned(
        gold_municipalities
    )
    if len(gyms_with_municipality) != len(gyms_cleaned):
        raise ValueError(
            "Gym spatial crossing must preserve one output row per cleaned facility."
        )
    rows = [
        _make_source_row(
            source="Population",
            raw=population_bronze,
            cleaned=population_cleaned,
            key_fields=["Municipios", "Periodo", "Sexo", "Edad"],
            duplicate_key_fields=["Municipios", "Periodo", "Sexo", "Edad"],
            candidate_municipalities=_population_candidate_codes(population_bronze),
            cross_records=population_cleaned,
            gold_municipality_codes=gold_municipality_codes,
            decision_adopted=(
                "Se agregan las observaciones municipales por año validadas; las "
                "filas rechazadas se guardan en processed/silver/failed/. Se "
                "excluyen de Gold los municipios sin datos válidos de renta."
            ),
        ),
        _make_source_row(
            source="Income",
            raw=income_bronze,
            cleaned=income_cleaned,
            key_fields=[
                "Municipios",
                "Periodo",
                "Indicadores de renta media",
            ],
            duplicate_key_fields=[
                "Municipios",
                "Periodo",
                "Distritos",
                "Secciones",
                "Indicadores de renta media",
            ],
            candidate_municipalities=_income_candidate_codes(income_bronze),
            cross_records=income_cleaned,
            gold_municipality_codes=gold_municipality_codes,
            decision_adopted=(
                "Se conservan únicamente los registros municipales válidos de renta "
                "neta media por persona; las filas rechazadas se guardan en "
                "processed/silver/failed/. Se excluyen de Gold los municipios sin "
                "datos válidos de población."
            ),
        ),
        _make_source_row(
            source="Gyms (OSM)",
            raw=gyms_bronze,
            cleaned=gyms_cleaned,
            key_fields=["osm_type", "osm_id", "latitude", "longitude"],
            duplicate_key_fields=["osm_type", "osm_id"],
            candidate_municipalities=None,
            cross_records=gyms_with_municipality,
            gold_municipality_codes=gold_municipality_codes,
            decision_adopted=(
                "De cada objeto OSM duplicado se conserva el registro más reciente; "
                "los registros no válidos se rechazan. Los establecimientos sin "
                "asignación espacial permanecen en Silver con el código municipal "
                "nulo y se excluyen de los recuentos de Gold."
            ),
        ),
        _make_source_row(
            source="CNIG boundaries",
            raw=cnig_bronze,
            cleaned=cnig_cleaned,
            key_fields=["nationalCode", "geometry"],
            duplicate_key_fields=["nationalCode"],
            candidate_municipalities=_cnig_candidate_codes(cnig_bronze),
            cross_records=cnig_cleaned,
            gold_municipality_codes=gold_municipality_codes,
            decision_adopted=(
                "Los límites municipales válidos de Andalucía se utilizan para el "
                "cruce espacial de gimnasios. Los límites de municipios sin datos "
                "válidos de población y renta permanecen en Silver, pero no se "
                "incluyen en Gold."
            ),
        ),
    ]
    result = pd.DataFrame(rows, columns=QUALITY_COLUMNS)
    for column in (
        "records",
        "records_after_cleaning",
        "records_with_null_key",
        "duplicate_records",
        "candidate_municipalities",
        "cleaned_municipalities",
        "records_eligible_for_cross",
        "records_crossed",
        "records_not_crossed",
    ):
        result[column] = result[column].astype("Int64")
    for column in (
        "pct_records_with_null_key",
        "municipality_retention_pct",
        "cross_pct",
    ):
        result[column] = result[column].astype("Float64")
    return result


def create_and_upload_quality_table(
    population_bronze: pd.DataFrame,
    population_cleaned: pd.DataFrame,
    income_bronze: pd.DataFrame,
    income_cleaned: pd.DataFrame,
    gyms_bronze: pd.DataFrame,
    gyms_cleaned: pd.DataFrame,
    cnig_bronze: pd.DataFrame,
    cnig_cleaned: pd.DataFrame,
    gyms_with_municipality: pd.DataFrame,
    gold_municipalities: pd.DataFrame,
) -> pd.DataFrame:
    """Build the source-quality table and persist it locally, to S3, or both."""
    report = create_quality_table(
        population_bronze,
        population_cleaned,
        income_bronze,
        income_cleaned,
        gyms_bronze,
        gyms_cleaned,
        cnig_bronze,
        cnig_cleaned,
        gyms_with_municipality,
        gold_municipalities,
    )
    settings = get_storage_settings()

    def persist(output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        report.to_parquet(output_path, index=False, compression="snappy")
        if settings.save_s3:
            upload_files_to_s3(
                [output_path],
                prefix=QUALITY_PREFIX,
                bucket_name=settings.bucket_name,
                region_name=settings.region_name,
            )

    if settings.save_locally:
        persist(QUALITY_TABLE_PATH)
    elif settings.save_s3:
        with TemporaryDirectory(prefix="market-expansion-quality-") as directory:
            persist(Path(directory) / QUALITY_TABLE_PATH.name)

    return report
