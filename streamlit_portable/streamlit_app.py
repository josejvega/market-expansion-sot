from __future__ import annotations

import json
import os
import sys
from html import escape
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
    BUSINESS_OUTPUTS,
    BUSINESS_RESULTS_PREFIX,
    load_audit_sample,
    MODEL_CANDIDATES_FILENAME,
    MODEL_CANDIDATES_S3_KEY,
    load_business_outputs,
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
    candidates_artifact: str = MODEL_CANDIDATES_S3_KEY,
    business_outputs: dict[str, pd.DataFrame] | None = None,
    business_source: str | None = None,
    audit: list[dict[str, object]] | None = None,
    audit_source: str | None = None,
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
    selection = top5_modelo(analysis) if has_model_candidates else analysis.iloc[0:0]
    baseline_ids = baseline["municipality_code"].astype(str).tolist()
    selection_ids = selection["municipality_code"].astype(str).tolist()
    published_business_rows: dict[str, dict[str, object]] = {}
    business_kpis: list[dict[str, object]] = []
    business_robustness: list[dict[str, object]] = []
    if business_outputs is not None:
        business_selection = business_outputs["selection"]
        business_baseline = business_outputs["baseline"]
        business_comparison = business_outputs["comparison"].set_index("estrategia")
        for strategy_key, label in (
            ("Baseline", "Baseline"),
            ("Modelo", "Modelo"),
        ):
            summary = business_comparison.loc[strategy_key]
            business_kpis.append(
                {
                    "strategy": label,
                    "selected": int(summary["centros_seleccionados"]),
                    "viable": int(summary["centros_viables"]),
                    "revenue_eur": float(
                        summary["facturacion_operativa_total_eur"]
                    ),
                    "margin_eur": float(
                        summary["margen_operativo_total_eur"]
                    ),
                    "losses_eur": float(summary["perdidas_operativas_totales_eur"]),
                    "demand_per_competitor": (
                        None
                        if pd.isna(summary["demanda_media_por_competidor"])
                        else float(summary["demanda_media_por_competidor"])
                    ),
                }
            )
        available_ids = set(analysis["municipality_code"].astype(str))
        selection_ids = business_selection["municipality_code"].astype(str).tolist()
        baseline_ids = business_baseline["municipality_code"].astype(str).tolist()
        unknown_ids = sorted(
            (set(selection_ids) | set(baseline_ids)).difference(available_ids)
        )
        if unknown_ids:
            raise ValueError(
                "Las salidas de negocio incluyen municipios ausentes de Gold: "
                f"{unknown_ids[:10]}."
            )
        gold_names = analysis.set_index("municipality_code")["municipality_name"]
        for table in (business_selection, business_baseline):
            for row in table.to_dict(orient="records"):
                identity = str(row["municipality_code"])
                if str(gold_names.loc[identity]) != str(row["municipality_name"]):
                    raise ValueError(
                        "El nombre municipal de las salidas de negocio no coincide "
                        f"con Gold para el código {identity}."
                    )
                published_business_rows[identity] = row
        robustness_by_code = business_outputs["robustness"].set_index(
            "municipality_code"
        )
        robustness_table = business_outputs["robustness"]
        total_scenarios = (
            int(robustness_table["combinaciones_totales"].max())
            if not robustness_table.empty
            else None
        )
        for identity in selection_ids:
            if identity not in robustness_by_code.index:
                continue
            row = robustness_by_code.loc[identity]
            business_robustness.append(
                {
                    "id": identity,
                    "name": str(row["municipality_name"]),
                    "appearances": int(row["apariciones"]),
                    "total_scenarios": total_scenarios,
                    "average_position": float(row["posicion_media"]),
                    "minimum_revenue_eur": (
                        None
                        if "fact_min" not in row.index or pd.isna(row["fact_min"])
                        else float(row["fact_min"])
                    ),
                }
            )

    params = parametros(scenario)
    central_weights = ESCENARIOS_PESOS["central"]
    def format_number_es(value: float, decimals: int = 0) -> str:
        return (
            f"{value:,.{decimals}f}"
            .replace(",", "\0")
            .replace(".", ",")
            .replace("\0", ".")
        )

    metadata = {
        "title": "Expansión de mercado · Andalucía",
        "region": "Andalucía",
        "period": f"Datos de población: {int(analysis['population_year'].max())}",
        "target_description": (
            "Comparativa municipal basada en la tabla Gold procesada del "
            "repositorio. Las cifras económicas son escenarios, no previsiones."
        ),
        "methodology": (
    "1 · MUNICIPIOS COMPARABLES\n"
    "K-means (k = 4) agrupa municipios según población 18–50, "
    "renta y crecimiento.\n\n"

    "2 · COMPETENCIA RELATIVA\n"
    "Calculamos los competidores equivalentes por cada 10.000 personas objetivo:\n"
    "D = [(Gimnasios + 0,1 × Otras instalaciones) / Población 18–50] × 10.000\n\n"

    "3 · OPORTUNIDADES\n"
    "Son candidatos los municipios con menor presión competitiva que la media "
    "de su cluster. Después se filtran por viabilidad económica y calidad "
    "del dato para obtener la recomendación final."
),
"business_formulas": [
    {
        "label": "Socios potenciales",
        "expression": (
            "población de 18–50 × penetración "
            f"({format_number_es(params['penetracion'] * 100, 1)} %)"
        ),
        "detail": "Mercado potencial estimado.",
    },
    {
        "label": "Cuota estimada",
        "expression": (
            "mínimo("
            f"{format_number_es(params['atractivo_nuevo'], 2)} ÷ "
            "(competencia ponderada + "
            f"{format_number_es(params['atractivo_nuevo'], 2)}), "
            f"{format_number_es(params['cuota_max'] * 100, 0)} %)"
        ),
        "detail": "Determina la parte del mercado potencial que podría captar el centro.",
    },
    {
        "label": "Facturación anual",
        "expression": (
            "socios captables × "
            f"{format_number_es(params['ticket_mensual'], 2)} € × 12"
        ),
        "detail": "Potencial anual estimado sin límite de capacidad.",
    },
    {
        "label": "Margen escalado",
        "expression": (
            "facturación − 556.000 × "
            "(0,6 + 0,4 × socios captables ÷ 2.600)"
        ),
        "detail": "El coste se escala con el volumen de socios captables.",
    },
],
        "baseline_description": (
            "Baseline de negocio publicado: cinco municipios con mayor población "
            "de 18–50 años dentro de los municipios asignados por el modelo."
            if business_outputs is not None
            else "Cinco municipios con mayor población de 18–50 años, ordenados "
            "por código municipal para desempatar."
        ),
        "selection_description": (
            "Selección central de negocio publicada por el proceso de evaluación "
            "y leída desde sus salidas CSV."
            if business_outputs is not None
            else (
                "La selección se limita a los candidatos publicados por el modelo."
                if has_model_candidates
                else "No se publica una selección de candidatos porque falta el "
                "artefacto del modelo."
            )
        ),
        "missing_artifacts": (
            []
            if has_model_candidates or business_outputs is not None
            else [candidates_artifact]
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
            f"Capacidad de referencia por centro: {params['capacidad']:,} socios.",
            f"Cuota máxima de captación: {params['cuota_max']:.0%}.",
            f"Atractivo relativo del nuevo centro: {params['atractivo_nuevo']:.2f}.",
            (
                "Pesos de competencia central: gimnasio "
                f"{central_weights['fitness_centre']:.1f}; otras instalaciones "
                f"{central_weights['sports_centre']:.1f}."
            ),
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
    if business_outputs is not None:
        metadata["business_kpis"] = business_kpis
        metadata["business_robustness"] = business_robustness
        metadata["sources"].append(
            {
                "label": (
                    f"Selección y baseline de negocio · {business_source or BUSINESS_RESULTS_PREFIX}"
                ),
                "url": None,
            }
        )
    if audit:
        metadata["sources"].append(
            {
                "label": f"Muestra manual de competencia · {audit_source or 'origen no indicado'}",
                "url": None,
            }
        )
        metadata["sources"].append(
            {
                "label": (
                    f"Comparación económica y sensibilidad · "
                    f"{BUSINESS_RESULTS_PREFIX}/"
                    f"{BUSINESS_OUTPUTS['comparison']} y "
                    f"{BUSINESS_OUTPUTS['robustness']}"
                ),
                "url": None,
            }
        )

    records = []
    for row in analysis.to_dict(orient="records"):
        identity = str(row["municipality_code"])
        business_row = published_business_rows.get(identity)
        cluster_value = row.get("cluster")
        cluster = (
            str(int(cluster_value))
            if pd.notna(cluster_value)
            else "Asignación no publicada"
        )
        is_candidate = bool(row.get("candidate_flag", False)) or identity in selection_ids
        if identity in selection_ids and business_outputs is not None:
            reason = str(
                business_row.get(
                    "motivo_calidad",
                    "Selección central de negocio publicada en S3.",
                )
            )
        elif has_model_candidates and is_candidate and row.get("viable", False):
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
                    float(business_row["demanda_por_comp"])
                    if business_row is not None
                    else (
                    None
                    if pd.isna(row["demanda_por_comp"])
                    else float(row["demanda_por_comp"])
                    )
                ),
"annual_revenue_eur": (
    float(business_row["facturacion_sin_tope_capacidad"])
    if business_row is not None
    else float(row["facturacion_anual"])
),
"annual_cost_eur": (
    float(business_row["coste_anual_escalado"])
    if business_row is not None
    else None
),
"annual_margin_eur": (
    float(business_row["margen_escalado_eur"])
    if business_row is not None
    else None
),
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
        "selection": selection_ids,
        "baseline": baseline_ids,
        "competitors": competitors or [],
        "audit": audit or [],
        "audit_source": audit_source,
        "market_checks": [],
        "simulation": {
            "model": "economic_scenario",
            "penetration": params["penetracion"],
            "monthly_ticket_eur": params["ticket_mensual"],
            "maximum_market_share": params["cuota_max"],
            "attractiveness": params["atractivo_nuevo"],
            "annual_cost_eur": params["coste_anual_club"],
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
    missing_artifacts = study["metadata"].get("missing_artifacts", [])
    warning = ""
    if missing_artifacts:
        missing = ", ".join(escape(str(artifact)) for artifact in missing_artifacts)
        warning = (
            '<div class="data-warning" role="status">'
            "<strong>Faltan datos del modelo.</strong> No está disponible "
            f"{missing}. El resto del dashboard se carga, pero las "
            "recomendaciones no estarán disponibles hasta publicar el artefacto."
            "</div>"
        )
    return (
        template.replace("__STYLES__", styles)
        .replace("__NOTICE__", warning)
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
        business_outputs, business_source = load_business_outputs(
            PROJECT_ROOT / "data" / "outputs"
        )
        audit, audit_source = load_audit_sample()
        study = build_study(
            municipalities,
            has_model_candidates,
            gold_source,
            competitors=competitors,
            candidates_artifact=candidates_s3_key or str(candidates_path),
            business_outputs=business_outputs,
            business_source=business_source,
            audit=audit,
            audit_source=audit_source,
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
