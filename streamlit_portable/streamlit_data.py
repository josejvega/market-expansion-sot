from __future__ import annotations

import math
from io import BytesIO
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import boto3
import geopandas as gpd
import pandas as pd
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

from src.common.storage import get_storage_settings
from src.procesado.common.paths import (
    GYMS_WITH_MUNICIPALITY_SILVER_PATH,
    MUNICIPALITY_BOUNDARIES_SILVER_PATH,
)

MODEL_CANDIDATES_FILENAME = "municipios_candidatos.parquet"
MODEL_CANDIDATES_S3_KEY = f"results/{MODEL_CANDIDATES_FILENAME}"
COMPETITOR_COLUMNS = {
    "osm_type",
    "osm_id",
    "latitude",
    "longitude",
    "tag_name",
}
GOLD_REQUIRED_COLUMNS = {
    "municipality_code",
    "municipality_name",
    "province",
    "population_year",
    "population_18_50",
    "population_growth_pct",
    "mean_net_income_per_person",
    "gyms_per_10k_18_50",
    "gyms_count",
    "other_sports_facilities_count",
}
INTEGER_COLUMNS = (
    "population_18_50",
    "gyms_count",
    "other_sports_facilities_count",
)
OPTIONAL_NUMERIC_COLUMNS = (
    "population_growth_pct",
    "mean_net_income_per_person",
    "gyms_per_10k_18_50",
)


def prepare_municipality_data(
    gold: pd.DataFrame,
    clusters: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, bool]:
    """Validate Gold data and optionally join a complete model cluster table."""
    missing = sorted(GOLD_REQUIRED_COLUMNS.difference(gold.columns))
    if missing:
        raise ValueError(f"Gold: faltan columnas requeridas: {missing}")

    municipalities = gold.copy()
    municipalities["municipality_code"] = (
        municipalities["municipality_code"].astype("string").str.strip()
    )
    codes = municipalities["municipality_code"]
    if codes.isna().any() or not codes.str.fullmatch(r"\d{5}").fillna(False).all():
        raise ValueError("Gold: municipality_code debe contener códigos de cinco dígitos.")
    if codes.duplicated().any():
        raise ValueError("Gold: municipality_code debe ser único.")

    for column in ("municipality_name", "province"):
        municipalities[column] = municipalities[column].astype("string").str.strip()
        if (
            municipalities[column].isna().any()
            or municipalities[column].eq("").any()
        ):
            raise ValueError(f"Gold: {column} no puede estar vacío.")

    for column in INTEGER_COLUMNS:
        values = pd.to_numeric(municipalities[column], errors="raise")
        if (
            values.isna().any()
            or values.lt(0).any()
            or values.mod(1).ne(0).any()
        ):
            raise ValueError(f"Gold: {column} debe ser un entero no negativo.")
        municipalities[column] = values.astype("int64")
    if municipalities["population_18_50"].eq(0).any():
        raise ValueError("Gold: population_18_50 debe ser positiva.")

    for column in OPTIONAL_NUMERIC_COLUMNS:
        values = pd.to_numeric(municipalities[column], errors="raise")
        if not values.dropna().map(math.isfinite).all():
            raise ValueError(f"Gold: {column} debe contener valores finitos o nulos.")
        if column != "population_growth_pct" and values.dropna().lt(0).any():
            raise ValueError(f"Gold: {column} no puede ser negativa.")
        municipalities[column] = values.astype("float64")

    if clusters is None:
        return municipalities, False

    expected_cluster_columns = {"municipality_code", "cluster"}
    missing = sorted(expected_cluster_columns.difference(clusters.columns))
    if missing:
        raise ValueError(f"Clusters: faltan columnas requeridas: {missing}")
    cluster_data = clusters.loc[:, ["municipality_code", "cluster"]].copy()
    cluster_data["municipality_code"] = (
        cluster_data["municipality_code"].astype("string").str.strip()
    )
    cluster_codes = cluster_data["municipality_code"]
    if (
        cluster_codes.isna().any()
        or not cluster_codes.str.fullmatch(r"\d{5}").fillna(False).all()
    ):
        raise ValueError("Clusters: municipality_code debe tener cinco dígitos.")
    if cluster_codes.duplicated().any():
        raise ValueError("Clusters: municipality_code debe ser único.")
    labels = pd.to_numeric(cluster_data["cluster"], errors="raise")
    if (
        labels.isna().any()
        or not labels.dropna().map(math.isfinite).all()
        or labels.lt(0).any()
        or labels.mod(1).ne(0).any()
    ):
        raise ValueError("Clusters: cluster debe ser un entero no negativo.")
    cluster_data["cluster"] = labels.astype("int64")

    if set(codes) != set(cluster_codes):
        raise ValueError("Clusters: los códigos deben coincidir exactamente con Gold.")
    joined = municipalities.merge(
        cluster_data,
        on="municipality_code",
        how="left",
        validate="one_to_one",
    )
    return joined, True


def prepare_model_candidates(
    municipalities: pd.DataFrame,
    candidates: pd.DataFrame | None,
) -> tuple[pd.DataFrame, bool]:
    """Join the model's candidate-only Parquet without requiring every cluster."""
    prepared = municipalities.copy()
    if candidates is None:
        prepared["candidate_flag"] = False
        prepared["cluster"] = pd.Series(
            pd.NA,
            index=prepared.index,
            dtype="Int64",
        )
        return prepared, False

    missing = sorted({"municipality_code", "cluster"}.difference(candidates.columns))
    if missing:
        raise ValueError(f"Candidatos del modelo: faltan columnas requeridas: {missing}")

    model = candidates.loc[:, ["municipality_code", "cluster"]].copy()
    model["municipality_code"] = (
        model["municipality_code"].astype("string").str.strip()
    )
    model_codes = model["municipality_code"]
    if (
        model_codes.isna().any()
        or not model_codes.str.fullmatch(r"\d{5}").fillna(False).all()
    ):
        raise ValueError(
            "Candidatos del modelo: municipality_code debe tener cinco dígitos."
        )
    if model_codes.duplicated().any():
        raise ValueError("Candidatos del modelo: municipality_code debe ser único.")

    labels = pd.to_numeric(model["cluster"], errors="raise")
    if (
        labels.isna().any()
        or not labels.dropna().map(math.isfinite).all()
        or labels.lt(0).any()
        or labels.mod(1).ne(0).any()
    ):
        raise ValueError(
            "Candidatos del modelo: cluster debe ser un entero no negativo."
        )
    model["cluster"] = labels.astype("int64")

    municipality_codes = prepared["municipality_code"].astype("string")
    unknown_codes = sorted(set(model_codes).difference(municipality_codes))
    if unknown_codes:
        raise ValueError(
            "Candidatos del modelo contiene municipios ausentes de Gold: "
            f"{unknown_codes[:10]}."
        )

    model["candidate_flag"] = True
    joined = prepared.merge(
        model,
        on="municipality_code",
        how="left",
        validate="one_to_one",
    )
    joined["candidate_flag"] = (
        joined["candidate_flag"].astype("boolean").fillna(False).astype(bool)
    )
    joined["cluster"] = joined["cluster"].astype("Int64")
    return joined, not model.empty


def prepare_competitor_records(points: gpd.GeoDataFrame) -> list[dict[str, object]]:
    """Convert the repository's municipality-assigned OSM Silver points for the map."""
    missing = sorted(COMPETITOR_COLUMNS.difference(points.columns))
    if missing:
        raise ValueError(f"Silver de gimnasios: faltan columnas requeridas: {missing}")

    records: list[dict[str, object]] = []
    for index, row in points.iterrows():
        osm_type = str(row["osm_type"]).strip().lower()
        osm_id = str(row["osm_id"]).strip()
        if osm_type not in {"node", "way", "relation"} or not osm_id:
            raise ValueError(
                f"Silver de gimnasios: identificador OSM inválido en fila {index}."
            )
        latitude = float(pd.to_numeric(row["latitude"], errors="raise"))
        longitude = float(pd.to_numeric(row["longitude"], errors="raise"))
        if (
            not math.isfinite(latitude)
            or not math.isfinite(longitude)
            or not -90 <= latitude <= 90
            or not -180 <= longitude <= 180
        ):
            raise ValueError(
                f"Silver de gimnasios: coordenadas inválidas en fila {index}."
            )
        name_value = row["tag_name"]
        name = (
            str(name_value).strip()
            if pd.notna(name_value) and str(name_value).strip()
            else f"Instalación OSM {osm_type}/{osm_id}"
        )
        records.append(
            {
                "name": name,
                "lat": latitude,
                "lon": longitude,
                "url": f"https://www.openstreetmap.org/{osm_type}/{osm_id}",
            }
        )
    return records


def add_municipality_coordinates(
    municipalities: pd.DataFrame,
    boundaries: gpd.GeoDataFrame,
) -> pd.DataFrame:
    """Join municipality representative points from Silver boundary polygons."""
    required = {"municipality_code", "geometry"}
    missing = sorted(required.difference(boundaries.columns))
    if missing:
        raise ValueError(f"Silver de límites: faltan columnas requeridas: {missing}")
    if boundaries.crs is None:
        raise ValueError("Silver de límites: el GeoParquet no declara su CRS.")

    boundary_data = boundaries.loc[:, ["municipality_code", "geometry"]].copy()
    boundary_data["municipality_code"] = (
        boundary_data["municipality_code"].astype("string").str.strip()
    )
    codes = boundary_data["municipality_code"]
    if codes.isna().any() or codes.duplicated().any():
        raise ValueError("Silver de límites: municipality_code debe ser único y no nulo.")
    if not codes.str.fullmatch(r"\d{5}").fillna(False).all():
        raise ValueError("Silver de límites: municipality_code debe tener cinco dígitos.")
    if boundary_data.geometry.isna().any() or boundary_data.geometry.is_empty.any():
        raise ValueError("Silver de límites: hay geometrías vacías o nulas.")

    if boundaries.crs.to_epsg() != 4326:
        boundary_data = gpd.GeoDataFrame(
            boundary_data,
            geometry="geometry",
            crs=boundaries.crs,
        ).to_crs("EPSG:4326")
    representative_points = boundary_data.geometry.representative_point()
    boundary_data["lat"] = representative_points.y
    boundary_data["lon"] = representative_points.x
    coordinates = boundary_data.loc[:, ["municipality_code", "lat", "lon"]]

    municipality_codes = municipalities["municipality_code"].astype("string")
    missing_codes = sorted(
        set(municipality_codes).difference(coordinates["municipality_code"])
    )
    if missing_codes:
        raise ValueError(
            "Faltan límites Silver para "
            f"{len(missing_codes)} municipios de Gold: {missing_codes[:10]}."
        )
    return municipalities.merge(
        coordinates,
        on="municipality_code",
        how="left",
        validate="one_to_one",
    )


def load_municipality_data(
    gold_path: Path,
    candidates_path: Path | None = None,
    boundaries_path: Path | None = None,
    candidates_s3_key: str | None = MODEL_CANDIDATES_S3_KEY,
    competitor_points_path: Path | None = None,
) -> tuple[pd.DataFrame, bool, str, list[dict[str, object]]]:
    """Read the repository's Gold, Silver, and model candidate artifacts."""
    gold_path = Path(gold_path)
    boundaries_path = Path(
        boundaries_path or MUNICIPALITY_BOUNDARIES_SILVER_PATH
    )
    competitor_points_path = Path(
        competitor_points_path or GYMS_WITH_MUNICIPALITY_SILVER_PATH
    )
    settings = get_storage_settings()
    if settings.bucket_name:
        client_options: dict[str, object] = {
            "config": Config(
                connect_timeout=10,
                read_timeout=120,
                retries={"max_attempts": 3, "mode": "standard"},
            )
        }
        if settings.region_name:
            client_options["region_name"] = settings.region_name
        try:
            client = boto3.client("s3", **client_options)
        except BotoCoreError as error:
            raise RuntimeError(
                "No se pudo crear el cliente S3. Comprueba la región y que haya "
                "credenciales AWS disponibles mediante un perfil local o un rol IAM."
            ) from error

        gold_key = f"gold/{gold_path.name}"
        silver_key = f"processed/silver/{boundaries_path.name}"
        competitor_points_key = (
            f"processed/silver/{competitor_points_path.name}"
        )
        try:
            gold_response = client.get_object(
                Bucket=settings.bucket_name,
                Key=gold_key,
            )
            with gold_response["Body"] as body:
                gold = pd.read_parquet(BytesIO(body.read()))
        except (BotoCoreError, ClientError) as error:
            raise RuntimeError(
                _s3_read_error_message(
                    settings.bucket_name,
                    gold_key,
                    error,
                )
            ) from error

        try:
            silver_response = client.get_object(
                Bucket=settings.bucket_name,
                Key=silver_key,
            )
            with silver_response["Body"] as body:
                boundaries = gpd.read_parquet(BytesIO(body.read()))
        except (BotoCoreError, ClientError) as error:
            raise RuntimeError(
                _s3_read_error_message(
                    settings.bucket_name,
                    silver_key,
                    error,
                )
            ) from error

        try:
            competitor_response = client.get_object(
                Bucket=settings.bucket_name,
                Key=competitor_points_key,
            )
            with competitor_response["Body"] as body:
                competitor_points = gpd.read_parquet(BytesIO(body.read()))
        except (BotoCoreError, ClientError) as error:
            raise RuntimeError(
                _s3_read_error_message(
                    settings.bucket_name,
                    competitor_points_key,
                    error,
                )
            ) from error

        candidates = None
        if candidates_s3_key:
            try:
                candidates_response = client.get_object(
                    Bucket=settings.bucket_name,
                    Key=candidates_s3_key,
                )
                with candidates_response["Body"] as body:
                    candidates = pd.read_parquet(BytesIO(body.read()))
            except (BotoCoreError, ClientError) as error:
                raise RuntimeError(
                    _s3_read_error_message(
                        settings.bucket_name,
                        candidates_s3_key,
                        error,
                    )
                ) from error

        source = f"S3 · {gold_key}"
    else:
        if not gold_path.is_file():
            raise FileNotFoundError(
                f"No está configurado S3_BUCKET y no se encuentra Gold local: {gold_path}"
            )
        if not boundaries_path.is_file():
            raise FileNotFoundError(
                "No está configurado S3_BUCKET y no se encuentran los límites "
                f"Silver locales: {boundaries_path}"
            )
        gold = pd.read_parquet(gold_path)
        boundaries = gpd.read_parquet(boundaries_path)
        source = f"Local · {gold_path.name}"

        if competitor_points_path.is_file():
            competitor_points = gpd.read_parquet(competitor_points_path)
        else:
            competitor_points = gpd.GeoDataFrame()

        candidates = None
        if candidates_path is not None and Path(candidates_path).is_file():
            candidates = pd.read_parquet(candidates_path)

    municipalities, _ = prepare_municipality_data(gold)
    municipalities, has_candidates = prepare_model_candidates(
        municipalities,
        candidates,
    )
    municipalities = add_municipality_coordinates(municipalities, boundaries)
    competitors = (
        prepare_competitor_records(competitor_points)
        if not competitor_points.empty
        else []
    )
    return municipalities, has_candidates, source, competitors


def _s3_read_error_message(
    bucket: str,
    key: str,
    error: BotoCoreError | ClientError,
) -> str:
    response = getattr(error, "response", {})
    code = response.get("Error", {}).get("Code", type(error).__name__)
    location = f"s3://{bucket}/{key}"
    if isinstance(error, NoCredentialsError):
        return (
            f"No hay credenciales AWS disponibles para leer {location}. "
            "En EC2, asocia un rol IAM a la instancia; en local, inicia sesión "
            "con AWS IAM Identity Center y configura AWS_PROFILE."
        )
    if code in {"AccessDenied", "403"}:
        return (
            f"AWS denegó la lectura de {location} (AccessDenied). Comprueba que "
            "el rol/perfil tenga s3:GetObject y que la política del bucket lo permita."
        )
    if code in {"NoSuchKey", "404"}:
        return f"No existe el objeto {location} (NoSuchKey). Comprueba su nombre en S3."
    return f"No se pudo leer {location} desde S3 ({code})."


def validate_study(study: dict) -> dict:
    def fail(path: str, message: str) -> None:
        raise ValueError(f"{path}: {message}")

    def text(value, path: str) -> None:
        if not isinstance(value, str) or not value.strip():
            fail(path, "se requiere texto no vacio")

    def numeric(value, path: str, minimum=None, maximum=None, nullable=False) -> None:
        if value is None and nullable:
            return
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            fail(path, "se requiere un numero finito" + (" o null" if nullable else ""))
        if minimum is not None and value < minimum or maximum is not None and value > maximum:
            fail(path, f"valor fuera de rango [{minimum}, {maximum}]")

    def records(key: str) -> list:
        value = study.get(key)
        if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
            fail(key, "se requiere una lista de objetos")
        return value

    def url(value, path: str) -> None:
        if value is not None and (not isinstance(value, str) or urlparse(value).scheme != "https" or not urlparse(value).netloc):
            fail(path, "usar una URL https valida o null")

    if not isinstance(study, dict) or type(study.get("schema_version")) is not int or study["schema_version"] != 1:
        fail("schema_version", "version soportada: 1")
    metadata = study.get("metadata")
    if not isinstance(metadata, dict):
        fail("metadata", "se requiere un objeto")
    for key in (
        "title",
        "region",
        "period",
        "target_description",
        "methodology",
        "revenue_method",
        "baseline_description",
        "selection_description",
    ):
        text(metadata.get(key), f"metadata.{key}")
    if "revenue_formula" in metadata:
        formula = metadata["revenue_formula"]
        if not isinstance(formula, dict):
            fail("metadata.revenue_formula", "se requiere un objeto label/numerator/denominator")
        for key in ("label", "denominator"):
            text(formula.get(key), f"metadata.revenue_formula.{key}")
        if not isinstance(formula.get("numerator"), list) or not formula["numerator"]:
            fail("metadata.revenue_formula.numerator", "se requiere una lista no vacia de factores")
        for index, factor in enumerate(formula["numerator"]):
            text(factor, f"metadata.revenue_formula.numerator[{index}]")
    if type(metadata.get("is_demo")) is not bool:
        fail("metadata.is_demo", "se requiere true o false")
    for key in ("assumptions", "limitations"):
        if not isinstance(metadata.get(key), list):
            fail(f"metadata.{key}", "se requiere una lista de textos")
        for index, value in enumerate(metadata[key]):
            text(value, f"metadata.{key}[{index}]")
    sources = metadata.get("sources")
    if not isinstance(sources, list):
        fail("metadata.sources", "se requiere una lista de objetos label/url")
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            fail(f"metadata.sources[{index}]", "se requiere un objeto label/url")
        text(source.get("label"), f"metadata.sources[{index}].label")
        url(source.get("url"), f"metadata.sources[{index}].url")
    municipalities = records("municipalities")
    ids = set()
    for index, row in enumerate(municipalities):
        path = f"municipalities[{index}]"
        for key in ("id", "name", "cluster", "reason"):
            text(row.get(key), f"{path}.{key}")
        if row["id"] in ids:
            fail(f"{path}.id", "identificador duplicado")
        ids.add(row["id"])
        numeric(row.get("lat"), f"{path}.lat", -90, 90)
        numeric(row.get("lon"), f"{path}.lon", -180, 180)
        if type(row.get("candidate")) is not bool:
            fail(f"{path}.candidate", "se requiere true o false")
        numeric(row.get("target_population"), f"{path}.target_population", 0)
        for key in ("income_eur", "tourism_beds", "competitor_count", "demand_per_competitor", "annual_revenue_eur", "revenue_low_eur", "revenue_high_eur"):
            if key not in row:
                fail(f"{path}.{key}", "campo requerido; usar null si se desconoce")
            numeric(row[key], f"{path}.{key}", 0, nullable=True)
        if row["competitor_count"] is not None and row["competitor_count"] % 1:
            fail(f"{path}.competitor_count", "se requiere un entero o null")
        if row["competitor_count"] == 0 and row["demand_per_competitor"] is not None:
            fail(f"{path}.demand_per_competitor", "usar null cuando no hay competidores")
        for key in ("growth_pct", "score"):
            if key not in row:
                fail(f"{path}.{key}", "campo requerido; usar null si se desconoce")
        numeric(row["growth_pct"], f"{path}.growth_pct", nullable=True)
        numeric(row["score"], f"{path}.score", 0, 100, nullable=True)
        low, central, high = (row[key] for key in ("revenue_low_eur", "annual_revenue_eur", "revenue_high_eur"))
        if (low is None) != (high is None):
            fail(path, "informar ambos limites de facturacion o ambos null")
        if low is not None and (low > high or central is not None and not low <= central <= high):
            fail(path, "el rango debe contener la facturacion central")
        for key in ("province", "coverage_note"):
            if key in row and not isinstance(row[key], str):
                fail(f"{path}.{key}", "se requiere texto")
    for key in ("selection", "baseline"):
        listing = study.get(key)
        if not isinstance(listing, list) or any(
            not isinstance(value, str) for value in listing
        ):
            fail(key, "se requiere una lista de identificadores")
        if key == "selection" and len(listing) > 5:
            fail(key, "se permiten como máximo cinco candidatos ordenados")
        if key == "baseline" and len(listing) != 5:
            fail(key, "se requieren cinco identificadores ordenados por prioridad")
        if len(set(listing)) != len(listing) or not set(listing).issubset(ids):
            fail(key, "usar municipios distintos presentes en municipalities")
        candidate_ids = {
            row["id"] for row in municipalities if row.get("candidate") is True
        }
        if key == "selection" and not set(listing).issubset(candidate_ids):
            fail(key, "la selección debe estar formada por candidatos publicados")
    for index, row in enumerate(records("competitors")):
        path = f"competitors[{index}]"
        text(row.get("name"), f"{path}.name")
        numeric(row.get("lat"), f"{path}.lat", -90, 90)
        numeric(row.get("lon"), f"{path}.lon", -180, 180)
        url(row.get("url"), f"{path}.url")
    for index, row in enumerate(records("audit")):
        path = f"audit[{index}]"
        for key in ("name", "municipality_name"):
            text(row.get(key), f"{path}.{key}")
        if row.get("status") not in ("pending", "unresolved", "correct", "incorrect"):
            fail(f"{path}.status", "usar pending, unresolved, correct o incorrect")
        url(row.get("evidence_url"), f"{path}.evidence_url")
        if row["status"] in ("correct", "incorrect"):
            text(row.get("evidence_url"), f"{path}.evidence_url")
            text(row.get("finding"), f"{path}.finding")
            try:
                date.fromisoformat(row.get("checked_date", ""))
            except (ValueError, TypeError):
                fail(f"{path}.checked_date", "usar una fecha YYYY-MM-DD")
    for key in ("census_sections", "isochrones"):
        if key not in study:
            continue
        collection = study[key]
        if not isinstance(collection, dict) or collection.get("type") != "FeatureCollection" or not isinstance(collection.get("features"), list):
            fail(key, "se requiere un GeoJSON FeatureCollection")
        from shapely.geometry import shape
        from shapely.errors import GEOSException

        feature_ids = set()
        for index, feature in enumerate(collection["features"]):
            path = f"{key}.features[{index}]"
            if not isinstance(feature, dict) or feature.get("type") != "Feature" or not isinstance(feature.get("properties"), dict):
                fail(path, "se requiere un Feature con properties")
            properties = feature["properties"]
            if not isinstance(properties.get("municipality_id"), str) or properties["municipality_id"] not in ids:
                fail(f"{path}.municipality_id", "municipio fuera del estudio")
            text(properties.get("source"), f"{path}.source")
            url(properties.get("source_url"), f"{path}.source_url")
            geometry = feature.get("geometry")
            if not isinstance(geometry, dict) or geometry.get("type") not in ("Polygon", "MultiPolygon"):
                fail(f"{path}.geometry", "usar Polygon o MultiPolygon WGS84")
            try:
                polygon = shape(geometry)
            except (TypeError, ValueError, KeyError, GEOSException):
                fail(f"{path}.geometry", "geometria no interpretable")
            if polygon.is_empty or not polygon.is_valid:
                fail(f"{path}.geometry", "geometria vacia o invalida")
            west, south, east, north = polygon.bounds
            numeric(west, f"{path}.west", -180, 180)
            numeric(east, f"{path}.east", -180, 180)
            numeric(south, f"{path}.south", -90, 90)
            numeric(north, f"{path}.north", -90, 90)
            if key == "census_sections":
                for field in ("id", "name"):
                    text(properties.get(field), f"{path}.{field}")
                if properties["id"] in feature_ids:
                    fail(f"{path}.id", "seccion duplicada")
                feature_ids.add(properties["id"])
                for field in ("target_population", "income_eur", "competitor_count"):
                    numeric(properties.get(field), f"{path}.{field}", 0, nullable=True)
            else:
                numeric(properties.get("minutes"), f"{path}.minutes", 0.1, 240)
                if properties.get("mode") not in ("walk", "bike", "drive"):
                    fail(f"{path}.mode", "usar walk, bike o drive")
                numeric(properties.get("origin_lat"), f"{path}.origin_lat", -90, 90)
                numeric(properties.get("origin_lon"), f"{path}.origin_lon", -180, 180)
    if "simulation" in study:
        config = study["simulation"]
        if not isinstance(config, dict) or config.get("model") != "equal_share":
            fail("simulation.model", "modelo soportado: equal_share; solo escenario, no prediccion")
        numeric(config.get("penetration"), "simulation.penetration", 0, 1)
        numeric(config.get("annual_ticket_eur"), "simulation.annual_ticket_eur", 0)
        weights = config.get("weights")
        if not isinstance(weights, dict) or set(weights) != {"demand", "income", "growth", "opportunity"}:
            fail("simulation.weights", "usar demand, income, growth y opportunity")
        for field, weight in weights.items():
            numeric(weight, f"simulation.weights.{field}", 0)
        if sum(weights.values()) <= 0:
            fail("simulation.weights", "al menos un peso debe ser positivo")
        profiles = config.get("target_profiles", [])
        if not isinstance(profiles, list):
            fail("simulation.target_profiles", "se requiere una lista")
        profile_ids = set()
        for index, profile in enumerate(profiles):
            path = f"simulation.target_profiles[{index}]"
            if not isinstance(profile, dict):
                fail(path, "se requiere un objeto id/label/populations")
            for field in ("id", "label"):
                text(profile.get(field), f"{path}.{field}")
            if profile["id"] == "current" or profile["id"] in profile_ids:
                fail(f"{path}.id", "identificador duplicado o reservado: current")
            profile_ids.add(profile["id"])
            populations = profile.get("populations")
            if not isinstance(populations, dict) or set(populations) != ids:
                fail(f"{path}.populations", "se requiere poblacion para todos los IDs del estudio")
            for identity, population in populations.items():
                numeric(population, f"{path}.populations.{identity}", 0)
    if "finance" in study:
        config = study["finance"]
        if not isinstance(config, dict):
            fail("finance", "se requiere un objeto")
        for field in ("annual_fixed_cost_eur", "annual_ticket_eur", "capacity_members"):
            numeric(config.get(field), f"finance.{field}", 0, nullable=True)
        numeric(config.get("variable_cost_ratio"), "finance.variable_cost_ratio", 0, 1, nullable=True)
        if config.get("variable_cost_ratio") == 1:
            fail("finance.variable_cost_ratio", "debe ser menor que 1")
    if "market_checks" in study:
        checks = records("market_checks")
        checked_ids = set()
        for index, check in enumerate(checks):
            path = f"market_checks[{index}]"
            identity = check.get("municipality_id")
            if not isinstance(identity, str) or identity not in ids or identity in checked_ids:
                fail(f"{path}.municipality_id", "municipio desconocido o duplicado")
            checked_ids.add(identity)
            if check.get("status") not in ("confirmed_zero", "competitors_found", "unresolved"):
                fail(f"{path}.status", "usar confirmed_zero, competitors_found o unresolved")
            url(check.get("source_url"), f"{path}.source_url")
            if check["status"] != "unresolved":
                for field in ("source_url", "finding", "scope"):
                    text(check.get(field), f"{path}.{field}")
                try:
                    date.fromisoformat(check.get("checked_date", ""))
                except (ValueError, TypeError):
                    fail(f"{path}.checked_date", "usar una fecha YYYY-MM-DD")
    return study