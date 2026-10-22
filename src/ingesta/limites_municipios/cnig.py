"""Download municipality boundaries for Andalusia from IGN/CNIG."""

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
CNIG_WFS_URL = "https://www.ign.es/wfs-inspire/unidades-administrativas"
OUTPUT_NAME = "municipality_boundaries_andalusia.csv"
CNIG_FILTER = """<fes:Filter xmlns:fes="http://www.opengis.net/fes/2.0"
xmlns:au="http://inspire.ec.europa.eu/schemas/au/4.0"
xmlns:xlink="http://www.w3.org/1999/xlink">
<fes:And>
<fes:PropertyIsLike wildCard="*" singleChar="?" escapeChar="!">
<fes:ValueReference>au:nationalCode</fes:ValueReference>
<fes:Literal>3401*</fes:Literal>
</fes:PropertyIsLike>
<fes:PropertyIsEqualTo>
<fes:ValueReference>au:nationalLevel/@xlink:href</fes:ValueReference>
<fes:Literal>https://inspire.ec.europa.eu/codelist/AdministrativeHierarchyLevel/4thOrder</fes:Literal>
</fes:PropertyIsEqualTo>
</fes:And>
</fes:Filter>"""


def _validate_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    # Validamos GeoJSON; una respuesta sin features tambien marca el final de la paginacion.
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise ValueError("CNIG did not return a GeoJSON FeatureCollection.")
    if payload == {"type": "FeatureCollection"}:
        return []
    features = payload.get("features")
    if not isinstance(features, list) or any(
        not isinstance(feature, dict)
        or not isinstance(feature.get("properties"), dict)
        for feature in features
    ):
        raise ValueError("CNIG returned an invalid features list.")
    return features


def _feature_to_row(
    feature: dict[str, Any],
    downloaded_at_utc: str,
) -> dict[str, Any]:
    # Conservamos las propiedades del CNIG y serializamos la geometria para guardarla en CSV.
    properties = {
        key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
        for key, value in feature["properties"].items()
    }
    geometry = feature.get("geometry")
    properties.update(
        {
            "geometry": json.dumps(geometry, ensure_ascii=False) if geometry else "",
            "source": "IGN/CNIG BDDAE",
            "downloaded_at_utc": downloaded_at_utc,
        }
    )
    return properties


def download_andalusia_municipality_boundaries_from_cnig(
    output_dir: Path = RAW_DIR,
    refresh: bool = False,
) -> Path:
    """Save cached WFS pages and an Andalusia-only municipality CSV."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = output_dir / ".cache" / "cnig" / "pages"
    rows = []
    downloads = []
    seen_units: set[str] = set()
    start_index, page_size, requested = 0, 500, False

    # El filtro WFS limita la consulta a municipios andaluces; descargamos la respuesta por paginas.
    with requests.Session() as session:
        session.headers.update({"User-Agent": "market-expansion-academy/1.0"})
        while True:
            params = {
                "SERVICE": "WFS",
                "VERSION": "2.0.0",
                "REQUEST": "GetFeature",
                "TYPENAMES": "au:AdministrativeUnit",
                "OUTPUTFORMAT": "application/geo+json",
                "SORTBY": "au:nationalCode",
                "COUNT": page_size,
                "STARTINDEX": start_index,
                "FILTER": CNIG_FILTER,
            }
            cache_path = cache_dir / f"{start_index:06d}.json"
            cached = (
                json.loads(cache_path.read_text(encoding="utf-8"))
                if cache_path.exists() and not refresh
                else None
            )
            if cached is not None and cached.get("params") == params:
                # Reutilizamos cada pagina cuando sus parametros coinciden con los actuales.
                features = _validate_payload(cached["payload"])
                LOGGER.info("Using cached CNIG page at index %s.", start_index)
            else:
                if requested:
                    time.sleep(1)
                requested = True
                LOGGER.info("Downloading CNIG page at index %s.", start_index)
                payload = request_json(
                    session,
                    CNIG_WFS_URL,
                    params,
                    _validate_payload,
                    source="CNIG",
                )
                features = _validate_payload(payload)
                # Guardamos cada pagina original para reanudar o inspeccionar la ingesta.
                cached = {
                    "params": params,
                    "url": CNIG_WFS_URL,
                    "downloaded_at_utc": utc_now(),
                    "payload": payload,
                }
                save_response(cached, cache_path)

            downloads.append(
                {
                    "start_index": start_index,
                    "url": cached["url"],
                    "downloaded_at_utc": cached["downloaded_at_utc"],
                    "file": str(cache_path.relative_to(output_dir)),
                }
            )
            for feature in features:
                # El codigo nacional debe ser unico para detectar solapamientos entre paginas.
                national_code = str(feature["properties"].get("nationalCode", ""))
                if not national_code or national_code in seen_units:
                    raise ValueError(
                        "CNIG returned a missing or duplicate nationalCode; "
                        "pagination cannot be verified."
                    )
                seen_units.add(national_code)
                rows.append(
                    _feature_to_row(feature, cached["downloaded_at_utc"])
                )
            if not features:
                break
            start_index += len(features)

    if not rows:
        raise RuntimeError("The CNIG WFS returned no Andalusian municipalities.")

    output_path = output_dir / OUTPUT_NAME
    # Exportamos las unidades y geometrías conservadas; el manifiesto documenta las paginas descargadas.
    save_csv(pd.DataFrame(rows), output_path)
    manifest = {
        "layer": "bronze",
        "source": "IGN/CNIG BDDAE",
        "license": "CC BY 4.0",
        "completed_at_utc": utc_now(),
        "downloads": downloads,
        "csv_file": output_path.name,
    }
    save_json(manifest, output_dir / "cnig_manifest.json")
    LOGGER.info("Saved %s Andalusian municipality boundaries to %s.", len(rows), output_path)
    return output_path
