from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components


APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
for import_path in (APP_DIR, PROJECT_ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from src.negocio.supuestos import ESCENARIOS_PESOS, parametros  # noqa: E402
from src.negocio.valor_negocio import (  # noqa: E402
    evaluar,
    top5_baseline,
    top5_modelo,
)
from src.procesado.common.paths import GOLD_TABLE_PATH  # noqa: E402
from streamlit_data import (  # noqa: E402
    MODEL_CANDIDATES_FILENAME,
    MODEL_CANDIDATES_S3_KEY,
    load_municipality_data,
)


DEFAULT_CANDIDATES_PATH = (
    PROJECT_ROOT / "data" / "results" / MODEL_CANDIDATES_FILENAME
)


def build_study(
    municipalities: pd.DataFrame,
    has_model_candidates: bool,
    gold_source: str,
    scenario: str = "central",
    weight_scenario: str = "central",
    revenue_rule: str = "C",
    competitors: list[dict[str, object]] | None = None,
) -> dict:
    """Adapt repository Gold, Silver, and model outputs to the dashboard."""
    analysis = evaluar(
        municipalities,
        escenario=scenario,
        pesos=weight_scenario,
        regla=revenue_rule,
        con_candidatos=False,
    )
    baseline = top5_baseline(analysis)
    selection = (
        top5_modelo(analysis)
        if has_model_candidates
        else analysis.iloc[0:0]
    )
    params = parametros(scenario)
    metadata = {
        "title": "Expansión de mercado · Andalucía",
        "region": "Andalucía",
        "period": f"Datos de población: {int(analysis['population_year'].max())}",
        "target_description": (
            "Comparativa municipal basada en la tabla Gold procesada del "
            "repositorio. Las cifras económicas son escenarios, no previsiones."
        ),
        "methodology": (
            "La población objetivo corresponde a residentes de 18–50 años. "
            "El crecimiento es el cambio porcentual de población total entre "
            "el primer y el último año disponible. La competencia ponderada "
            "aplica los pesos configurados en el análisis de negocio."
        ),
        "baseline_description": (
            "Cinco municipios con mayor población de 18–50 años, ordenados "
            "por código municipal para desempatar."
        ),
        "selection_description": (
            "La selección se limita a los candidatos publicados por el modelo."
            if has_model_candidates
            else "No se publica una selección de candidatos porque falta el "
            "artefacto del modelo."
        ),
        "revenue_method": (
            f"Escenario {scenario} con la regla de facturación "
            f"{'cuota por atractivo' if revenue_rule == 'C' else 'demanda no cubierta'}. "
            "Facturación anual estimada = socios estimados en el centro × "
            "cuota mensual sin IVA × 12 meses. "
            "La facturación se calcula con los supuestos del módulo de negocio; "
            "no son ventas observadas."
        ),
        "is_demo": False,
        "assumptions": [
            f"Penetración central del escenario: {params['penetracion']:.1%}.",
            f"Cuota mensual sin IVA: {params['ticket_mensual']:.2f} €.",
            f"Coste anual de referencia: {params['coste_anual_club']:,.0f} €.",
            "El recuento OSM de instalaciones no es una auditoría de competidores.",
        ],
        "limitations": [
            "Las coordenadas del mapa representan un punto interior de cada polígono municipal Silver; no son una ubicación de gimnasio.",
            "Gold agrupa gimnasios y otras instalaciones deportivas, sin distinguir todos sus tipos.",
            "El artefacto del modelo publica candidatos, no clusters para todos los municipios; el resto aparece como asignación no publicada.",
            "Gold y Silver no incluyen auditorías de mercado, turismo ni secciones censales.",
            "La facturación y la viabilidad son escenarios basados en supuestos, no predicciones.",
        ],
        "sources": [
            {"label": f"Gold procesada · {gold_source}", "url": None},
            {
                "label": (
                    f"Candidatos · {MODEL_CANDIDATES_S3_KEY}"
                    if has_model_candidates
                    else "Candidatos del modelo · no disponibles"
                ),
                "url": None,
            },
            {
                "label": (
                    "Límites municipales Silver · processed/silver/"
                    "limites_municipales_andalucia.parquet"
                ),
                "url": None,
            },
            {
                "label": (
                    "Gimnasios geolocalizados · processed/silver/"
                    "gyms_with_municipality_andalusia.parquet"
                ),
                "url": None,
            },
        ],
    }

    records = []
    for row in analysis.to_dict(orient="records"):
        identity = str(row["municipality_code"])
        cluster_value = row.get("cluster")
        cluster = (
            str(int(cluster_value))
            if pd.notna(cluster_value)
            else "Asignación no publicada"
        )
        is_candidate = bool(row.get("candidate_flag", False))
        if has_model_candidates and is_candidate and row.get("viable", False):
            reason = (
                "Menos competencia ponderada por población que la media de su "
                "grupo; supera el umbral de viabilidad."
            )
        elif has_model_candidates and is_candidate:
            reason = (
                "Menos competencia ponderada por población que la media de su grupo."
            )
        elif has_model_candidates:
            reason = "No cumple el criterio de competencia relativa del modelo."
        else:
            reason = "El artefacto de candidatos del modelo no está disponible."
        records.append(
            {
                "id": identity,
                "name": row["municipality_name"],
                "province": row["province"],
                "cluster": cluster,
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
                "candidate": is_candidate,
                "reason": reason,
                "target_population": int(row["population_18_50"]),
                "growth_pct": (
                    None
                    if pd.isna(row["population_growth_pct"])
                    else float(row["population_growth_pct"])
                ),
                "income_eur": (
                    None
                    if pd.isna(row["mean_net_income_per_person"])
                    else float(row["mean_net_income_per_person"])
                ),
                "tourism_beds": None,
                "competitor_count": int(
                    row["gyms_count"] + row["other_sports_facilities_count"]
                ),
                "competitors_weighted": float(row["competidores_pond"]),
                "demand_per_competitor": (
                    None
                    if pd.isna(row["demanda_por_comp"])
                    else float(row["demanda_por_comp"])
                ),
                "annual_revenue_eur": float(row["facturacion_anual"]),
                "revenue_low_eur": None,
                "revenue_high_eur": None,
                "score": None,
                "coverage_note": (
                    "Recuento de instalaciones de Gold; no verifica la ausencia "
                    "de competencia."
                ),
            }
        )

    return {
        "schema_version": 1,
        "metadata": metadata,
        "municipalities": records,
        "selection": selection["municipality_code"].astype(str).tolist(),
        "baseline": baseline["municipality_code"].astype(str).tolist(),
        "competitors": competitors or [],
        "audit": [],
        "market_checks": [],
        "simulation": {
            "model": "equal_share",
            "penetration": params["penetracion"],
            "annual_ticket_eur": params["ticket_mensual"] * 12,
            "weights": {
                "demand": 1.0,
                "income": 1.0,
                "growth": 1.0,
                "opportunity": 0.0,
            },
            "target_profiles": [],
        },
        "finance": {
            "annual_fixed_cost_eur": params["coste_anual_club"],
            "variable_cost_ratio": None,
            "annual_ticket_eur": params["ticket_mensual"] * 12,
            "capacity_members": params["capacidad"],
        },
    }


def chart_style(figure: go.Figure, height: int = 370) -> go.Figure:
    figure.update_layout(
        height=height,
        template="plotly_white",
        font={"family": "IBM Plex Sans, sans-serif", "size": 12, "color": "#242128"},
        margin={"l": 8, "r": 20, "t": 15, "b": 15},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        legend={"title_text": "", "orientation": "h", "y": 1.12, "x": 0},
        separators=",.",
        hoverlabel={"bgcolor": "white", "font_color": "#242128"},
    )
    figure.update_xaxes(gridcolor="#e9e5ed", zeroline=False)
    figure.update_yaxes(gridcolor="#e9e5ed", zeroline=False)
    return figure


def render_study(study: dict) -> str:
    municipalities = pd.DataFrame(study["municipalities"])
    plotted = municipalities.dropna(subset=["income_eur", "growth_pct"])
    if plotted.empty:
        market = go.Figure()
        market.add_annotation(
            text="Sin datos de renta y crecimiento disponibles",
            showarrow=False,
        )
    else:
        market = px.scatter(
            plotted,
            x="income_eur",
            y="growth_pct",
            size="target_population",
            hover_name="name",
            size_max=34,
            labels={
                "income_eur": "Renta neta anual por persona (EUR)",
                "growth_pct": "Crecimiento de poblacion en 5 anos (%)",
                "target_population": "Publico objetivo",
            },
        )
        market.update_traces(
            marker={
                "color": "#2976ad",
                "opacity": 0.65,
                "line": {"width": 1, "color": "white"},
            }
        )
        market.add_hline(y=0, line_dash="dot", line_color="#96909c")
    market_html = chart_style(market, 390).to_html(
        full_html=False,
        include_plotlyjs="cdn",
        div_id="market-bubbles",
        config={"displayModeBar": False, "responsive": True},
    )

    styles = (APP_DIR / "web" / "streamlit.css").read_text(encoding="utf-8-sig")
    payload = (
        json.dumps(study, ensure_ascii=True, allow_nan=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    template = (APP_DIR / "web" / "streamlit.html").read_text(encoding="utf-8")
    analysis = (APP_DIR / "web" / "streamlit_analysis.js").read_text(
        encoding="utf-8"
    )
    return (
        template.replace("__STYLES__", styles)
        .replace("__MARKET__", market_html)
        .replace("__ANALYSIS__", analysis)
        .replace("__DATA__", payload)
    )


@st.cache_data(ttl=300, show_spinner=False)
def load_data(
    gold_path: str,
    candidates_path: str,
    gold_mtime_ns: int,
    candidates_mtime_ns: int | None,
    candidates_s3_key: str | None,
) -> tuple[pd.DataFrame, bool, str, list[dict[str, object]]]:
    return load_municipality_data(
        Path(gold_path),
        Path(candidates_path) if candidates_mtime_ns is not None else None,
        candidates_s3_key=candidates_s3_key,
    )


def main() -> None:
    st.set_page_config(
        page_title="Grupo 5 · Market Expansion",
        page_icon=":material/exercise:",
        layout="wide",
    )
    gold_path = Path(
        os.environ.get("GYM_GOLD_PATH", str(GOLD_TABLE_PATH))
    ).expanduser()
    candidates_path = Path(
        os.environ.get("GYM_CANDIDATES_PATH", str(DEFAULT_CANDIDATES_PATH))
    ).expanduser()
    candidates_s3_key = os.environ.get(
        "GYM_CANDIDATES_S3_KEY",
        MODEL_CANDIDATES_S3_KEY,
    ) or None
    try:
        gold_mtime_ns = gold_path.stat().st_mtime_ns if gold_path.is_file() else 0
        candidates_mtime_ns = (
            candidates_path.stat().st_mtime_ns if candidates_path.is_file() else None
        )
        municipalities, has_model_candidates, gold_source, competitors = load_data(
            str(gold_path),
            str(candidates_path),
            gold_mtime_ns,
            candidates_mtime_ns,
            candidates_s3_key,
        )
        study = build_study(
            municipalities,
            has_model_candidates,
            gold_source,
            competitors=competitors,
        )
        html = render_study(study)
    except (OSError, ImportError, RuntimeError, ValueError) as error:
        st.error(f"No se pudieron cargar los datos del repositorio: {error}")
        st.stop()

    st.markdown(
        """<style>
html,body,[data-testid=stAppViewContainer],[data-testid=stMain]{overflow:hidden}
.block-container{padding:0!important;max-width:none!important}
[data-testid=stHeader],footer{display:none}
[data-testid=stMainBlockContainer]>[data-testid=stVerticalBlock]{gap:0}
iframe[title="st.iframe"]{height:100dvh;width:100%;border:0;display:block}
</style>""",
        unsafe_allow_html=True,
    )
    components.html(html, height=1000, scrolling=True)


if __name__ == "__main__":
    main()
