"""Download gym and sports-centre data for Andalusia from OpenStreetMap."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from ..common.ingestion import (
    RAW_DIR,
    request_json,
    save_csv,
    save_json,
    save_response,
    utc_now,
)

LOGGER = logging.getLogger(__name__)
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OUTPUT_NAME = "gyms_andalusia.csv"
PROVINCES = {
    "ES-AL": "Almería",
    "ES-CA": "Cádiz",
    "ES-CO": "Córdoba",
    "ES-GR": "Granada",
    "ES-H": "Huelva",
    "ES-J": "Jaén",
    "ES-MA": "Málaga",
    "ES-SE": "Sevilla",
}
OVERPASS_QUERY = """[out:json][timeout:120];
area["ISO3166-2"="{province_code}"]["admin_level"="6"]->.province;
.province out count;
(
  nwr[leisure=fitness_centre](area.province);
  nwr[leisure=sports_centre](area.province);
  nwr[sport=fitness](area.province);
);
out center tags;""".strip()
BASE_COLUMNS = [
    "osm_type",
    "osm_id",
    "province_code",
    "province",
    "latitude",
    "longitude",
    "source",
    "downloaded_at_utc",
]


def _validate_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    # Comprobamos que Overpass devolvio una respuesta completa para un area provincial.
    if not isinstance(payload, dict) or not isinstance(payload.get("elements"), list):
        raise ValueError("Overpass did not return a valid elements list.")
    if payload.get("remark"):
        raise ValueError(f"Overpass returned an incomplete response: {payload['remark']}")
    elements = payload["elements"]
    if any(not isinstance(element, dict) for element in elements):
        raise ValueError("Overpass returned invalid elements.")
    area_counts = [
        element for element in elements if element.get("type") == "count"
    ]
    if (
        len(area_counts) != 1
        or area_counts[0].get("tags", {}).get("areas") != "1"
    ):
        raise ValueError("Could not verify exactly one provincial area.")
    records = [element for element in elements if element.get("type") != "count"]
    if any(
        element.get("type") not in {"node", "way", "relation"}
        or not isinstance(element.get("id"), int)
        or not isinstance(element.get("tags", {}), dict)
        for element in records
    ):
        raise ValueError("Overpass returned an element without valid type, ID, or tags.")
    return records


def _element_to_row(
    element: dict[str, Any],
    province_code: str,
    province: str,
    downloaded_at_utc: str,
) -> dict[str, Any]:
    # Los tags se mantienen en columnas propias; las coordenadas vienen del elemento o de su centro.
    center = element.get("center") or {}
    latitude = element.get("lat", center.get("lat"))
    longitude = element.get("lon", center.get("lon"))
    row = {
        f"tag_{key}": value
        for key, value in element.get("tags", {}).items()
    }
    row.update(
        {
            "osm_type": element["type"],
            "osm_id": element["id"],
            "province_code": province_code,
            "province": province,
            "latitude": latitude,
            "longitude": longitude,
            "source": "OpenStreetMap",
            "downloaded_at_utc": downloaded_at_utc,
        }
    )
    return row


def download_andalusia_gyms_from_osm(
    output_dir: Path = RAW_DIR,
    refresh: bool = False,
) -> Path:
    """Download and save Andalusian gym records, with resumable province caches."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = output_dir / ".cache" / "osm" / "provinces"
    rows = []
    downloads = []
    requested = False

    # La consulta de Overpass se acota provincia a provincia dentro de Andalucía.
    with requests.Session() as session:
        session.headers.update({"User-Agent": "market-expansion-academy/1.0"})
        for province_code, province in PROVINCES.items():
            query = OVERPASS_QUERY.format(province_code=province_code)
            cache_path = cache_dir / f"{province_code}.json"
            cached = (
                json.loads(cache_path.read_text(encoding="utf-8"))
                if cache_path.exists() and not refresh
                else None
            )
            if cached is not None and cached.get("query") == query:
                # Reutilizamos la respuesta si la consulta en cache sigue siendo la misma.
                elements = _validate_payload(cached["payload"])
                LOGGER.info("Using cached OSM response for %s.", province)
            else:
                if requested:
                    time.sleep(10)
                requested = True
                LOGGER.info("Downloading OSM data for %s.", province)
                payload = request_json(
                    session,
                    OVERPASS_URL,
                    {"data": query},
                    _validate_payload,
                    source="OpenStreetMap",
                    method="POST",
                    timeout=(15, 180),
                )
                elements = _validate_payload(payload)
                # Guardamos la respuesta original para poder reanudar sin repetir la descarga.
                cached = {
                    "province": province_code,
                    "query": query,
                    "url": OVERPASS_URL,
                    "downloaded_at_utc": utc_now(),
                    "payload": payload,
                }
                save_response(cached, cache_path)

            # Aplanamos los elementos y añadimos la provincia y la fecha de esta respuesta.
            for element in elements:
                rows.append(
                    _element_to_row(
                        element,
                        province_code,
                        province,
                        cached["downloaded_at_utc"],
                    )
                )
            downloads.append(
                {
                    "province": province_code,
                    "url": cached["url"],
                    "downloaded_at_utc": cached["downloaded_at_utc"],
                    "file": str(cache_path.relative_to(output_dir)),
                }
            )

    output_path = output_dir / OUTPUT_NAME
    # Unimos las etiquetas variables de OSM en columnas y guardamos el CSV Bronze.
    dataframe = pd.DataFrame(rows)
    if dataframe.empty:
        dataframe = pd.DataFrame(columns=BASE_COLUMNS)
        LOGGER.warning("OpenStreetMap returned no matching gym records in Andalusia.")
    else:
        dataframe = dataframe.reindex(
            columns=BASE_COLUMNS
            + sorted(column for column in dataframe.columns if column.startswith("tag_"))
        )
    save_csv(dataframe, output_path)
    manifest = {
        "layer": "bronze",
        "source": "OpenStreetMap contributors",
        "license": "ODbL",
        "completed_at_utc": utc_now(),
        "downloads": downloads,
        "csv_file": output_path.name,
    }
    save_json(manifest, output_dir / "osm_manifest.json")
    LOGGER.info("Saved %s Andalusian OSM records to %s.", len(rows), output_path)
    return output_path
