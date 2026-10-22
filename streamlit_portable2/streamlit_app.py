from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st
import streamlit.components.v1 as components

from streamlit_data import validate_study


ROOT = Path(__file__).resolve().parent


def chart_style(figure: go.Figure, height: int = 370) -> go.Figure:
    figure.update_layout(
        height=height, template="plotly_white", font={"family": "IBM Plex Sans, sans-serif", "size": 12, "color": "#242128"},
        margin={"l": 8, "r": 20, "t": 15, "b": 15}, paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff", legend={"title_text": "", "orientation": "h", "y": 1.12, "x": 0},
        separators=",.", hoverlabel={"bgcolor": "white", "font_color": "#242128"},
    )
    figure.update_xaxes(gridcolor="#e9e5ed", zeroline=False)
    figure.update_yaxes(gridcolor="#e9e5ed", zeroline=False)
    return figure


def render_study(study: dict) -> str:
    municipalities = pd.DataFrame(study["municipalities"])
    plotted = municipalities.dropna(subset=["income_eur", "growth_pct"])
    if plotted.empty:
        market = go.Figure()
        market.add_annotation(text="Sin datos de renta y crecimiento disponibles", showarrow=False)
    else:
        market = px.scatter(plotted, x="income_eur", y="growth_pct", size="target_population",
                            hover_name="name", size_max=34,
                            labels={"income_eur": "Renta neta anual por persona (EUR)",
                                    "growth_pct": "Crecimiento de poblacion en 5 anos (%)",
                                    "target_population": "Publico objetivo"})
        market.update_traces(marker={"color": "#2976ad", "opacity": .65, "line": {"width": 1, "color": "white"}})
        market.add_hline(y=0, line_dash="dot", line_color="#96909c")
    market_html = chart_style(market, 390).to_html(full_html=False, include_plotlyjs="cdn", div_id="market-bubbles",
                                                config={"displayModeBar": False, "responsive": True})
    styles = (ROOT / "web" / "streamlit.css").read_text(encoding="utf-8-sig")
    payload = json.dumps(study, ensure_ascii=True, allow_nan=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    template = (ROOT / "web" / "streamlit.html").read_text(encoding="utf-8")
    analysis = (ROOT / "web" / "streamlit_analysis.js").read_text(encoding="utf-8")
    return template.replace("__STYLES__", styles).replace("__MARKET__", market_html).replace("__ANALYSIS__", analysis).replace("__DATA__", payload)


def main() -> None:
    st.set_page_config(page_title="Grupo 5 · Market Expansion", page_icon=":material/exercise:", layout="wide")
    study_url = os.environ.get("GYM_STUDY_URL", "").strip()
    try:
        parsed_url = urlparse(study_url)
        if parsed_url.scheme != "https" or not parsed_url.netloc:
            raise ValueError("Configura GYM_STUDY_URL con la URL HTTPS del JSON de estudio.")
        response = requests.get(study_url, timeout=(5, 30))
        response.raise_for_status()
        study = validate_study(response.json())
        html = render_study(study)
    except (OSError, ValueError, requests.RequestException) as error:
        st.error(f"No se pudo cargar el estudio: {error}")
        st.info("Comprueba GYM_STUDY_URL y el contrato de datos. No se sustituyen datos invalidos por un estudio de ejemplo.")
        st.stop()
    st.markdown("""<style>
html,body,[data-testid=stAppViewContainer],[data-testid=stMain]{overflow:hidden}
.block-container{padding:0!important;max-width:none!important}
[data-testid=stHeader],footer{display:none}
[data-testid=stMainBlockContainer]>[data-testid=stVerticalBlock]{gap:0}
iframe[title="st.iframe"]{height:100dvh;width:100%;border:0;display:block}
</style>""", unsafe_allow_html=True)
    components.html(html, height=1000, scrolling=True)


if __name__ == "__main__":
    main()