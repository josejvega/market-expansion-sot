from __future__ import annotations

import math
from datetime import date
from urllib.parse import urlparse


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
    for key in ("title", "region", "period", "target_description", "methodology", "revenue_method", "baseline_description"):
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
        if not isinstance(listing, list) or len(listing) != 5 or any(not isinstance(value, str) for value in listing):
            fail(key, "se requieren cinco identificadores, ordenados por prioridad")
        if len(set(listing)) != 5 or not set(listing).issubset(ids):
            fail(key, "usar cinco municipios distintos presentes en municipalities")
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