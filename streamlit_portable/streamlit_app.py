from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st


APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
for import_path in (APP_DIR, PROJECT_ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from src.negocio.supuestos import ESCENARIOS_PESOS  # noqa: E402
from src.negocio.valor_negocio import (  # noqa: E402
    evaluar,
    top5_baseline,
    top5_facturacion,
    top5_modelo,
)
from streamlit_data import load_municipality_data  # noqa: E402


DEFAULT_GOLD_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "gold"
    / "tabla_oro_municipios_andalucia.parquet"
)
DEFAULT_CLUSTERS_PATH = PROJECT_ROOT / "data" / "resultados" / "clusters.csv"


@st.cache_data(ttl=300, show_spinner=False)
def load_data(
    gold_path: str,
    clusters_path: str,
    gold_mtime_ns: int,
    clusters_mtime_ns: int | None,
) -> tuple[pd.DataFrame, bool, str]:
    return load_municipality_data(
        Path(gold_path),
        Path(clusters_path) if clusters_mtime_ns is not None else None,
    )


def _business_table(frame: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "municipality_name",
        "province",
        "population_18_50",
        "competidores_pond",
        "demanda_por_comp",
        "facturacion_anual",
        "margen_eur",
    ]
    if "cluster" in frame.columns:
        columns.insert(2, "cluster")
    return frame.loc[:, columns].rename(
        columns={
            "municipality_name": "Municipio",
            "province": "Provincia",
            "cluster": "Cluster",
            "population_18_50": "Población 18–50",
            "competidores_pond": "Competencia ponderada",
            "demanda_por_comp": "Demanda por competidor",
            "facturacion_anual": "Facturación anual estimada",
            "margen_eur": "Margen estimado",
        }
    )


def main() -> None:
    st.set_page_config(
        page_title="Market Expansion · Andalucía",
        page_icon="🏋️",
        layout="wide",
    )
    st.title("Market Expansion · Andalucía")
    st.caption(
        "Análisis municipal basado en los datos procesados del repositorio. "
        "Las cifras económicas son escenarios del modelo, no previsiones."
    )

    gold_path = Path(os.environ.get("GYM_GOLD_PATH", str(DEFAULT_GOLD_PATH))).expanduser()
    clusters_path = Path(
        os.environ.get("GYM_CLUSTERS_PATH", str(DEFAULT_CLUSTERS_PATH))
    ).expanduser()
    try:
        gold_mtime_ns = (
            gold_path.stat().st_mtime_ns if gold_path.is_file() else 0
        )
        clusters_mtime_ns = (
            clusters_path.stat().st_mtime_ns if clusters_path.is_file() else None
        )
        municipalities, has_clusters, gold_source = load_data(
            str(gold_path),
            str(clusters_path),
            gold_mtime_ns,
            clusters_mtime_ns,
        )
    except (OSError, ImportError, RuntimeError, ValueError) as error:
        st.error(f"No se pudieron cargar los datos del repositorio: {error}")
        st.stop()

    st.sidebar.header("Escenario de negocio")
    scenario = st.sidebar.selectbox(
        "Supuestos económicos",
        ("central", "bajo", "alto"),
        format_func=str.capitalize,
    )
    weight_scenario = st.sidebar.selectbox(
        "Ponderación de competencia",
        tuple(ESCENARIOS_PESOS),
        index=tuple(ESCENARIOS_PESOS).index("central"),
        format_func=lambda value: value.replace("_", " ").capitalize(),
    )
    revenue_rule = st.sidebar.selectbox(
        "Regla de facturación",
        ("C", "demanda_no_cubierta"),
        format_func=lambda value: (
            "Cuota por atractivo" if value == "C" else "Demanda no cubierta"
        ),
    )
    analysis = evaluar(
        municipalities,
        escenario=scenario,
        pesos=weight_scenario,
        regla=revenue_rule,
        con_candidatos=has_clusters,
    )

    if has_clusters:
        st.sidebar.success("Clusters del modelo cargados.")
    else:
        st.sidebar.info(
            "Sin clusters: se muestran el baseline y el ranking por facturación; "
            "la selección del modelo requiere ejecutar el clustering."
        )
    st.sidebar.caption(f"Gold: {gold_source}")

    provinces = sorted(analysis["province"].dropna().unique().tolist())
    selected_provinces = st.sidebar.multiselect(
        "Provincias",
        provinces,
        default=provinces,
    )
    filtered = analysis.loc[analysis["province"].isin(selected_provinces)]

    overview, business, methodology = st.tabs(
        ("Resumen y municipios", "Escenario de negocio", "Datos y metodología")
    )

    with overview:
        viable_count = int(analysis["viable"].sum())
        first, second, third, fourth = st.columns(4)
        first.metric("Municipios", f"{len(analysis):,}".replace(",", "."))
        second.metric(
            "Población de 18–50",
            f"{int(analysis['population_18_50'].sum()):,}".replace(",", "."),
        )
        third.metric(
            "Gimnasios OSM",
            f"{int(analysis['gyms_count'].sum()):,}".replace(",", "."),
        )
        fourth.metric("Viables en este escenario", str(viable_count))
        st.caption(
            f"Facturación y viabilidad calculadas con el escenario "
            f"{scenario} y la regla seleccionada en el panel."
        )

        chart_data = filtered.dropna(
            subset=["mean_net_income_per_person", "population_growth_pct"]
        )
        if chart_data.empty:
            st.info("No hay municipios con renta y crecimiento para representar.")
        else:
            chart_data = chart_data.copy()
            if "cluster" in chart_data.columns:
                chart_data["cluster"] = chart_data["cluster"].astype("string")
            chart = px.scatter(
                chart_data,
                x="mean_net_income_per_person",
                y="population_growth_pct",
                size="population_18_50",
                color="cluster" if "cluster" in chart_data.columns else "province",
                hover_name="municipality_name",
                hover_data=["province", "gyms_count", "other_sports_facilities_count"],
                labels={
                    "mean_net_income_per_person": "Renta neta media por persona (€)",
                    "population_growth_pct": "Crecimiento de población (%)",
                    "population_18_50": "Población de 18–50",
                    "province": "Provincia",
                    "cluster": "Cluster",
                },
            )
            chart.update_layout(
                template="plotly_white",
                xaxis={"gridcolor": "#e9e5ed"},
                yaxis={"gridcolor": "#e9e5ed"},
                legend_title_text="",
            )
            st.plotly_chart(chart, use_container_width=True)

        st.subheader("Municipios")
        display_columns = [
            "municipality_code",
            "municipality_name",
            "province",
            "population_18_50",
            "population_growth_pct",
            "mean_net_income_per_person",
            "gyms_count",
            "other_sports_facilities_count",
            "gyms_per_10k_18_50",
        ]
        if "cluster" in filtered.columns:
            display_columns.append("cluster")
        st.dataframe(
            filtered.loc[:, display_columns].rename(
                columns={
                    "municipality_code": "Código",
                    "municipality_name": "Municipio",
                    "province": "Provincia",
                    "population_18_50": "Población 18–50",
                    "population_growth_pct": "Crecimiento (%)",
                    "mean_net_income_per_person": "Renta media (€)",
                    "gyms_count": "Gimnasios",
                    "other_sports_facilities_count": "Otras instalaciones",
                    "gyms_per_10k_18_50": "Gimnasios / 10.000 personas",
                    "cluster": "Cluster",
                }
            ),
            hide_index=True,
            use_container_width=True,
        )

    with business:
        st.subheader("Selecciones para el escenario")
        st.caption(
            "Las clasificaciones usan todos los municipios de Gold; "
            "el filtro provincial solo afecta al resumen y a la tabla municipal."
        )
        baseline = top5_baseline(analysis)
        revenue_top = top5_facturacion(analysis)
        if has_clusters:
            selected = top5_modelo(analysis)
            st.markdown("**Modelo: candidatos viables**")
            if selected.empty:
                st.info("Ningún municipio cumple los criterios del modelo en este escenario.")
            else:
                st.dataframe(
                    _business_table(selected),
                    hide_index=True,
                    use_container_width=True,
                )
        st.markdown("**Referencia: cinco municipios con más población objetivo**")
        st.dataframe(
            _business_table(baseline),
            hide_index=True,
            use_container_width=True,
        )
        st.markdown("**Cinco municipios viables con mayor facturación estimada**")
        if revenue_top.empty:
            st.info("Ningún municipio resulta viable en este escenario.")
        else:
            st.dataframe(
                _business_table(revenue_top),
                hide_index=True,
                use_container_width=True,
            )
        st.caption(
            "La facturación, la demanda y la viabilidad son resultados del modelo "
            "de escenarios y de sus supuestos; no representan ventas observadas."
        )

    with methodology:
        st.subheader("Fuentes leídas")
        st.code(gold_source, language=None)
        st.write(
            "La Gold Parquet contiene los valores municipales procesados de "
            "población, crecimiento, renta y recuentos de instalaciones."
        )
        if has_clusters:
            st.code(str(clusters_path), language=None)
            st.write("Los clusters se incorporan por código municipal.")
        else:
            st.write(
                "No se encontró el CSV de clusters. El dashboard sigue funcionando "
                "sin presentar una selección de modelo."
            )
        st.subheader("Limitaciones")
        st.markdown(
            "- La fuente de competencia es OpenStreetMap; un recuento cero no "
            "demuestra que no existan competidores.\n"
            "- Gold no contiene coordenadas municipales ni auditorías de mercado.\n"
            "- Las estimaciones económicas dependen de los supuestos de "
            "`src/negocio/supuestos.py` y no son predicciones."
        )


if __name__ == "__main__":
    main()
