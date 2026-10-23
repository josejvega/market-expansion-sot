"""
ejecutar.py  -  T5 de principio a fin.
Uso (desde la raíz del repo):  python -m src.negocio.ejecutar

Entrada:
  - data/processed/gold/tabla_oro_municipios_andalucia.parquet
  - data/results/clusters.parquet (asignaciones del notebook del modelo)
Salida (data/outputs/, ignorado por Git):
  - municipios_evaluados_<pesos>.csv, baseline_<pesos>.csv, top_facturacion_<pesos>.csv
  - si hay clusters: seleccion_modelo_<pesos>.csv, comparacion_<pesos>.csv,
    sensibilidad_detalle.csv, sensibilidad_frecuencias.csv
"""
import io
from pathlib import Path

import boto3
import numpy as np
import pandas as pd
from botocore.exceptions import BotoCoreError, ClientError

from src.common.storage import get_storage_settings, s3_uri_for
from src.common.upload_to_s3 import parse_s3_uri
from src.modelo.modelo import CLUSTER_ASSIGNMENTS_PATH, RESULTS_PREFIX
from src.procesado.common.paths import DATA_DIR, GOLD_TABLE_PATH

from .supuestos import parametros
from .valor_negocio import (
    evaluar, sensibilidad, top5_baseline, top5_diversificado_clusters,
    top5_facturacion, top5_modelo, seleccionar_modelo_con_calidad,
)

ORO = GOLD_TABLE_PATH
QUALITY_TABLE_PATH = DATA_DIR / "processed" / "quality" / "municipios_dudosos_gimnasios.parquet"
SALIDA = DATA_DIR / "outputs"
NECESARIAS = ["municipality_code", "municipality_name", "population_18_50",
              "gyms_count", "other_sports_facilities_count"]
ESCENARIOS_ANTERIORES = ("solo_gimnasios", "central", "todo_igual")
PREFIJOS_T5_ANTERIORES = (
    "municipios_evaluados", "baseline", "top_facturacion", "seleccion_modelo",
    "comparacion",
)
ARCHIVOS_T5_GESTIONADOS = {
    f"{prefijo}_{escenario}.csv"
    for prefijo in PREFIJOS_T5_ANTERIORES
    for escenario in ESCENARIOS_ANTERIORES
} | {
    "municipios_evaluados_variantes_central.csv",
    "seleccion_modelo_variantes_central.csv",
    "comparacion_variantes_central.csv",
    "seleccion_diversificada_clusters_central.csv",
    "comparacion_estrategias_central.csv",
    "sensibilidad_detalle.csv",
    "sensibilidad_frecuencias.csv",
    "resumen_negocio.md",
}


def formato_numero(valor, decimales=0):
    """Formatea cifras con separadores habituales en español."""
    if pd.isna(valor):
        return "—"
    return (f"{valor:,.{decimales}f}".replace(",", "\0")
            .replace(".", ",").replace("\0", "."))


def formato_con_sufijo(valor, decimales, sufijo):
    texto = formato_numero(valor, decimales)
    return texto if texto == "—" else texto + sufijo


def tabla_markdown(encabezados, filas):
    """Construye una tabla Markdown sin dependencias opcionales."""
    filas = [[str(valor).replace("|", "\\|").replace("\n", " ") for valor in fila]
             for fila in filas]
    lineas = ["| " + " | ".join(encabezados) + " |",
              "| " + " | ".join(["---"] * len(encabezados)) + " |"]
    lineas.extend("| " + " | ".join(fila) + " |" for fila in filas)
    return "\n".join(lineas)


def limpiar_salidas_t5(directorio=SALIDA):
    """Elimina solo nombres de salida conocidos y gestionados por T5."""
    if not directorio.exists():
        return []
    eliminados = []
    for nombre in sorted(ARCHIVOS_T5_GESTIONADOS):
        ruta = directorio / nombre
        if ruta.is_file():
            ruta.unlink()
            eliminados.append(nombre)
    return eliminados


ESTRATEGIAS = {
    "Baseline": "baseline",
    "Máxima facturación sin clusters": "maxima_facturacion",
    "Modelo A oficial": "modelo_a",
    "Alternativa diversificada por clusters": "diversificada",
}
ESTRATEGIAS_REPORTE = {
    "Baseline": "baseline",
    "Modelo": "modelo_a",
    "Alternativa diversificada por clusters": "diversificada",
}


def tabla_seleccion(tabla, incluir_diagnosticos=False, incluir_motivo=False):
    """Formatea una estrategia en una tabla Markdown orientada a decisión."""
    encabezados = [
        "Posición", "Municipio", "Cluster", "Población 18-50", "Competidores ponderados",
        "Facturación anual con tope (EUR)", "Facturación anual sin tope (EUR)",
        "Margen anual (EUR)", "quality_flag",
        "weighted_observed_vs_expected_pct", "quality_status",
    ]
    if incluir_diagnosticos:
        encabezados.extend([
            "Competencia por 10.000", "Media de competencia del cluster",
            "Colchón de demanda",
        ])
    if incluir_motivo:
        encabezados.append("Motivo de selección")

    filas = []
    for indice, (_, fila) in enumerate(tabla.iterrows(), start=1):
        posicion = fila.get("posicion", indice)
        valores = [
            formato_numero(posicion), fila["municipality_name"],
            formato_numero(fila.get("cluster", np.nan)),
            formato_numero(fila["population_18_50"]),
            formato_numero(fila["competidores_pond"], 1),
            formato_numero(fila["facturacion_anual"]),
            formato_numero(fila["facturacion_sin_tope_capacidad"]),
            formato_numero(fila["margen_eur"]),
            "True" if bool(fila.get("quality_flag", False)) else "False",
            formato_con_sufijo(
                fila.get("weighted_observed_vs_expected_pct", np.nan), 2, "%"
            ),
            fila.get("quality_status", ""),
        ]
        if incluir_diagnosticos:
            valores.extend([
                formato_numero(fila["comp_per_10k_18_50"], 2),
                formato_numero(fila["media_cluster_comp_per_10k"], 2),
                formato_con_sufijo(fila["colchon_demanda_pct"] * 100, 1, "%"),
            ])
        if incluir_motivo:
            valores.append(fila.get("motivo_seleccion", ""))
        filas.append(valores)
    if not filas:
        filas = [["—"] * len(encabezados)]
    return tabla_markdown(encabezados, filas)


def tabla_baseline(tabla):
    """Formatea el baseline obligatorio, incluyendo viabilidad y avisos."""
    encabezados = [
        "Posición", "Municipio", "Cluster", "Población 18-50",
        "Competidores ponderados", "Facturación anual con tope (EUR)",
        "Facturación anual sin tope (EUR)", "Margen anual (EUR)", "Viable", "quality_flag",
        "weighted_observed_vs_expected_pct", "quality_status",
    ]
    filas = []
    for posicion, (_, fila) in enumerate(tabla.iterrows(), start=1):
        filas.append([
            formato_numero(posicion), fila["municipality_name"],
            formato_numero(fila.get("cluster", np.nan)),
            formato_numero(fila["population_18_50"]),
            formato_numero(fila["competidores_pond"], 1),
            formato_numero(fila["facturacion_anual"]),
            formato_numero(fila["facturacion_sin_tope_capacidad"]),
            formato_numero(fila["margen_eur"]),
            "Sí" if fila["viable"] else "No",
            "True" if bool(fila.get("quality_flag", False)) else "False",
            formato_con_sufijo(
                fila.get("weighted_observed_vs_expected_pct", np.nan), 2, "%"
            ),
            fila.get("quality_status", ""),
        ])
    if not filas:
        filas = [["—"] * len(encabezados)]
    return tabla_markdown(encabezados, filas)


def tabla_municipios_validacion(pendientes):
    """Tabla de oportunidades descartadas o pendientes por calidad."""
    encabezados = [
        "Posición económica original", "Municipio", "Competidores ponderados",
        "Gimnasios equivalentes esperados", "Cobertura ponderada",
        "Facturación anual sin tope (EUR)", "Facturación con tope (EUR)",
        "Motivo", "Estado de calidad",
    ]
    filas = [[
        formato_numero(fila.get("posicion_ranking_precalidad", np.nan)),
        fila["municipality_name"],
        formato_numero(fila.get("competidores_pond", np.nan), 1),
        formato_numero(fila.get("expected_gyms", np.nan), 2),
        formato_con_sufijo(
            fila.get("weighted_observed_vs_expected_pct", np.nan), 2, "%"
        ),
        formato_numero(fila.get("facturacion_sin_tope_capacidad", np.nan)),
        formato_numero(fila.get("facturacion_anual", np.nan)),
        fila.get("motivo_calidad", ""),
        fila.get("quality_status", ""),
    ] for _, fila in pendientes.iterrows()]
    if not filas:
        filas = [["—"] * len(encabezados)]
    return tabla_markdown(encabezados, filas)

def tabla_indicadores_complementarios(selecciones):
    encabezados = [
        "Estrategia", "Municipio", "Socios captables", "Ratio de capacidad",
        "Potencial teórico sin límite de capacidad (EUR)",
    ]
    filas = []
    for estrategia, clave in ESTRATEGIAS_REPORTE.items():
        for _, fila in selecciones[clave].iterrows():
            filas.append([
                estrategia,
                fila["municipality_name"],
                formato_numero(fila.get("socios_captables", np.nan)),
                formato_con_sufijo(fila.get("ratio_capacidad", np.nan), 2, "×"),
                formato_numero(fila.get("facturacion_sin_tope_capacidad", np.nan)),
            ])
    if not filas:
        filas = [["—"] * len(encabezados)]
    return tabla_markdown(encabezados, filas)


def resumir_estrategia(nombre, seleccion):
    """Calcula las métricas comparables de una selección de centros."""
    avisos = ~seleccion.get(
        "quality_flag", pd.Series(False, index=seleccion.index)
    ).fillna(False).astype(bool)
    nombres_aviso = sorted(
        seleccion.loc[avisos, "municipality_name"].astype(str).unique()
    )
    clusters = int(seleccion["cluster"].nunique()) if "cluster" in seleccion else 0
    clusters_sin_candidato = seleccion.attrs.get("cluster_sin_candidato_viable", [])

    def suma(columna):
        if columna not in seleccion:
            return 0.0
        return float(pd.to_numeric(seleccion[columna], errors="coerce").sum())

    def media(columna):
        if seleccion.empty or columna not in seleccion:
            return np.nan
        return float(pd.to_numeric(seleccion[columna], errors="coerce").mean())

    return {
        "estrategia": nombre,
        "centros_seleccionados": len(seleccion),
        "centros_viables": int(seleccion["viable"].fillna(False).sum())
        if "viable" in seleccion else 0,
        "facturacion_anual_total_con_tope_eur": suma("facturacion_anual"),
        "margen_operativo_anual_total_eur": suma("margen_eur"),
        "perdidas_operativas_totales_eur": suma("perdidas_eur"),
        "margen_medio_por_centro_eur": media("margen_eur"),
        "demanda_media_por_competidor": media("demanda_por_comp"),
        "municipios_con_aviso_osm": ", ".join(nombres_aviso),
        "clusters_representados": clusters,
        "cluster_sin_candidato_viable": ", ".join(map(str, clusters_sin_candidato)),
    }


def crear_comparacion_estrategias(selecciones):
    """Construye la tabla exportable de las cuatro estrategias centrales."""
    return pd.DataFrame([
        resumir_estrategia(nombre, selecciones[clave])
        for nombre, clave in ESTRATEGIAS.items()
    ])


def tabla_comparacion_estrategias(comparacion):
    encabezados = [
        "Estrategia", "Centros seleccionados", "Centros viables",
        "Facturación anual total con tope (EUR)", "Margen operativo anual total (EUR)",
        "Pérdidas operativas totales (EUR)", "Margen medio por centro (EUR)",
        "Demanda media por competidor", "Municipios con quality_flag=True",
        "Clusters representados",
    ]
    columnas = [
        "estrategia", "centros_seleccionados", "centros_viables",
        "facturacion_anual_total_con_tope_eur", "margen_operativo_anual_total_eur",
        "perdidas_operativas_totales_eur", "margen_medio_por_centro_eur",
        "demanda_media_por_competidor", "municipios_con_aviso_osm", "clusters_representados",
    ]
    filas = []
    for fila in comparacion[columnas].itertuples(index=False, name=None):
        valores = list(fila)
        for indice in (1, 2, 9):
            valores[indice] = formato_numero(valores[indice])
        for indice in (3, 4, 5, 6):
            valores[indice] = formato_con_sufijo(valores[indice], 0, " EUR")
        valores[7] = formato_numero(valores[7], 1)
        valores[8] = valores[8] or "—"
        filas.append(valores)
    return tabla_markdown(encabezados, filas)


def tabla_robustez(frecuencias, detalle=None):
    """Resume estabilidad y muestra la calidad fija del escenario central."""
    encabezados = [
        "Municipio", "Apariciones en escenarios", "Posición media cuando aparece",
        "Facturación mínima cuando aparece (EUR)", "Robustez",
        "Calidad del dato en escenario central",
    ]
    filas = [[
        fila.municipality_name,
        formato_numero(fila.apariciones),
        formato_numero(fila.posicion_media, 1),
        formato_numero(fila.fact_min),
        fila.robustez,
        fila.quality_status_central,
    ] for fila in frecuencias.head(10).itertuples(index=False)]
    if not filas:
        filas = [["—"] * len(encabezados)]
    return tabla_markdown(encabezados, filas)

def nota_tope_capacidad():
    return (
        "Los cálculos utilizan como referencia un club estándar de 2.600 socios. En este "
        "escenario la facturación máxima operativa sería aproximadamente 697.944 €/año. "
        "Municipios con demanda superior podrían admitir formatos de mayor capacidad, "
        "varias aperturas o estrategias comerciales distintas, aspectos fuera del alcance actual."
    )


def _identificadores(tabla):
    columna = "municipality_code" if "municipality_code" in tabla else "municipality_name"
    return set(tabla[columna].astype(str))


def aporte_clusters(maxima_facturacion, modelo_a, evaluacion):
    """Explica el efecto del filtro oficial de candidatos sobre el Top 5 central."""
    codigos_maximos = _identificadores(maxima_facturacion)
    codigos_modelo = _identificadores(modelo_a)
    descartados = int((evaluacion["viable"] & ~evaluacion["candidate_flag"]).sum())
    if codigos_maximos == codigos_modelo and codigos_modelo:
        texto = (
            "El filtro por clusters no modifica el Top 5 económico en el escenario central. "
            "Su aportación es validar que los municipios seleccionados tienen menos "
            "competencia relativa que la media de su grupo, no cambiar el ranking."
        )
    elif codigos_maximos == codigos_modelo:
        texto = (
            "El filtro por clusters no modifica el resultado: ninguna estrategia encuentra "
            "municipios viables para seleccionar."
        )
    else:
        referencia = maxima_facturacion.set_index("municipality_code")["municipality_name"]
        seleccion = modelo_a.set_index("municipality_code")["municipality_name"]
        entran = sorted(seleccion.loc[list(codigos_modelo - codigos_maximos)].tolist())
        salen = sorted(referencia.loc[list(codigos_maximos - codigos_modelo)].tolist())
        texto = (
            "El filtro por clusters cambia la selección. "
            f"Entran: {', '.join(entran) or 'ninguno'}; "
            f"salen: {', '.join(salen) or 'ninguno'}."
        )
    return (
        f"{texto} Municipios viables descartados porque candidate_flag es False: "
        f"{descartados}."
    )


def aporte_diversificacion(modelo_a, diversificada):
    codigos_modelo = _identificadores(modelo_a)
    codigos_diversificados = _identificadores(diversificada)
    nombres_modelo = modelo_a.set_index("municipality_code")["municipality_name"]
    nombres_diversificados = diversificada.set_index("municipality_code")["municipality_name"]
    entran = sorted(nombres_diversificados.loc[
        list(codigos_diversificados - codigos_modelo)
    ].tolist())
    salen = sorted(nombres_modelo.loc[
        list(codigos_modelo - codigos_diversificados)
    ].tolist())
    diferencia_facturacion = (
        diversificada["facturacion_anual"].sum() - modelo_a["facturacion_anual"].sum()
    )
    diferencia_margen = diversificada["margen_eur"].sum() - modelo_a["margen_eur"].sum()
    clusters_modelo = int(modelo_a["cluster"].nunique())
    clusters_diversificada = int(diversificada["cluster"].nunique())
    etiqueta_clusters_modelo = "cluster" if clusters_modelo == 1 else "clusters"
    etiqueta_clusters_diversificada = "cluster" if clusters_diversificada == 1 else "clusters"
    clusters_sin = diversificada.attrs.get("cluster_sin_candidato_viable", [])
    texto_clusters_sin = ", ".join(map(str, clusters_sin)) or "ninguno"
    return (
        f"Modelo representa {clusters_modelo} {etiqueta_clusters_modelo} y la alternativa "
        f"representa {clusters_diversificada} {etiqueta_clusters_diversificada}. "
        f"La alternativa selecciona {len(diversificada)} municipios, con como máximo un cluster repetido. "
        f"Entran en la alternativa: {', '.join(entran) or 'ninguno'}; "
        f"salen: {', '.join(salen) or 'ninguno'}. Diferencia de facturación con tope: "
        f"{formato_con_sufijo(diferencia_facturacion, 0, ' EUR')}; diferencia de margen: "
        f"{formato_con_sufijo(diferencia_margen, 0, ' EUR')}. Clusters sin candidato viable: "
        f"{texto_clusters_sin}. Es una opción de cartera para representar perfiles municipales, "
        "no una obligación del challenge ni una mejora automática frente a la maximización económica."
    )


def resumen_perfiles_clusters(evaluacion, diversificada):
    datos = evaluacion.copy()
    datos["candidate_flag"] = datos["candidate_flag"].fillna(False).astype(bool)
    datos["viable"] = datos["viable"].fillna(False).astype(bool)
    datos["candidato_viable"] = datos["candidate_flag"] & datos["viable"]
    perfiles = datos.groupby("cluster").agg(
        municipios=("municipality_code", "size"),
        poblacion=("population_18_50", "median"),
        crecimiento=("population_growth_pct", "median"),
        renta=("mean_net_income_per_person", "median"),
        competencia=("comp_per_10k_18_50", "median"),
        candidatos=("candidate_flag", "sum"),
        candidatos_viables=("candidato_viable", "sum"),
    )
    elegibles = perfiles.index[perfiles["candidatos_viables"].gt(0)].tolist()
    sin_candidato_viable = perfiles.index[
        perfiles["candidatos_viables"].eq(0)
    ].tolist()
    lineas = [
        "### Estado provisional y perfil de clusters", "",
        f"**Provisional:** solo {len(elegibles)} de {len(perfiles)} clusters tienen "
        f"candidatos que cumplen a la vez candidate_flag y viabilidad. La alternativa "
        f"selecciona {len(diversificada)} municipios en "
        f"{diversificada['cluster'].nunique()} clusters; no se relajan los filtros ni "
        "se fuerzan cinco plazas.",
        "La candidatura mide competencia inferior a la media del propio cluster; la "
        "viabilidad es distinta y exige facturación anual con tope suficiente para "
        "cubrir el coste del centro.",
    ]
    if "socios_break_even" in datos and "umbral_facturacion" in datos:
        socios_equilibrio = pd.to_numeric(
            datos["socios_break_even"], errors="coerce"
        ).dropna()
        facturacion_equilibrio = pd.to_numeric(
            datos["umbral_facturacion"], errors="coerce"
        ).dropna()
        if not socios_equilibrio.empty and not facturacion_equilibrio.empty:
            lineas[-1] += (
                f" En este escenario, el umbral es de unos "
                f"{formato_numero(socios_equilibrio.iloc[0])} socios captables y "
                f"{formato_numero(facturacion_equilibrio.iloc[0])} EUR al año."
            )

    ejemplos = []
    for cluster in sin_candidato_viable:
        candidatos = datos.loc[
            datos["cluster"].eq(cluster) & datos["candidate_flag"]
        ].sort_values("facturacion_anual", ascending=False, kind="mergesort")
        if candidatos.empty:
            ejemplos.append(f"cluster {cluster}: no tiene candidatos")
            continue
        mejor = candidatos.iloc[0]
        ejemplos.append(
            f"cluster {cluster}: {mejor['municipality_name']} alcanza "
            f"{formato_numero(mejor['socios_captables'])} socios, "
            f"{formato_numero(mejor['facturacion_anual'])} EUR de facturación y "
            f"{formato_numero(mejor['margen_eur'])} EUR de margen"
        )
    if ejemplos:
        lineas.extend([
            "Entre los clusters sin candidatos viables, el candidato con mayor "
            "facturación de cada uno queda así: " + "; ".join(ejemplos) + ".",
        ])

    encabezados = [
        "Cluster", "Municipios", "Población 18-50 mediana", "Crecimiento mediano",
        "Renta mediana (EUR)", "Competencia mediana por 10.000", "Candidatos",
        "Candidatos viables",
    ]
    filas = []
    for cluster, perfil in perfiles.iterrows():
        filas.append([
            formato_numero(cluster), formato_numero(perfil["municipios"]),
            formato_numero(perfil["poblacion"]),
            formato_con_sufijo(perfil["crecimiento"], 2, "%"),
            formato_numero(perfil["renta"]),
            formato_numero(perfil["competencia"], 2),
            formato_numero(perfil["candidatos"]),
            formato_numero(perfil["candidatos_viables"]),
        ])
    lineas.extend(["", tabla_markdown(encabezados, filas), "", "Lectura de perfiles:"])
    for cluster, perfil in perfiles.iterrows():
        rasgos = []
        if perfil["municipios"] == perfiles["municipios"].max():
            rasgos.append("es el grupo más numeroso")
        poblacion = perfil["poblacion"]
        if np.isclose(poblacion, perfiles["poblacion"].max()):
            rasgos.append("tiene la mayor población 18-50 mediana")
        elif np.isclose(poblacion, perfiles["poblacion"].min()):
            rasgos.append("tiene la menor población 18-50 mediana")
        elif poblacion < perfiles["poblacion"].median():
            rasgos.append("tiene una población 18-50 mediana baja")
        crecimiento = perfil["crecimiento"]
        if np.isclose(crecimiento, perfiles["crecimiento"].max()):
            rasgos.append("destaca por el mayor crecimiento mediano")
        elif crecimiento < 0:
            rasgos.append("presenta crecimiento mediano negativo")
        elif crecimiento > 0:
            rasgos.append("presenta crecimiento mediano positivo")
        if np.isclose(perfil["renta"], perfiles["renta"].max()):
            rasgos.append("tiene la mayor renta mediana")
        elif np.isclose(perfil["renta"], perfiles["renta"].min()):
            rasgos.append("tiene la menor renta mediana")
        if np.isclose(perfil["competencia"], perfiles["competencia"].max()):
            rasgos.append("registra la mayor competencia mediana")
        viables = int(perfil["candidatos_viables"])
        etiqueta_viables = "candidato viable" if viables == 1 else "candidatos viables"
        rasgos.append(f"aporta {viables} {etiqueta_viables}")
        lineas.append(f"- Cluster {formato_numero(cluster)}: " + "; ".join(rasgos) + ".")
    return "\n".join(lineas)


def validaciones_osm(selecciones):
    lineas = ["La ausencia de gimnasios en OSM no demuestra que no exista competencia real."]
    hay_avisos = False
    for estrategia, clave in ESTRATEGIAS.items():
        seleccion = selecciones[clave]
        avisos = seleccion.get("aviso_calidad", pd.Series("", index=seleccion.index))
        nombres = sorted(seleccion.loc[
            avisos.fillna("").astype(str).str.strip().ne(""), "municipality_name"
        ].astype(str).unique())
        if nombres:
            hay_avisos = True
            lineas.append(f"- {estrategia}: {', '.join(nombres)}.")
    if hay_avisos:
        lineas.append(
            "Los municipios señalados requieren validación con una segunda fuente antes "
            "de recomendar una inversión."
        )
    else:
        lineas.append("Ninguna estrategia tiene municipios seleccionados con aviso OSM.")
    return "\n".join(lineas)


def resumen_capacidad(selecciones, capacidad):
    lineas = []
    for estrategia, clave in ESTRATEGIAS.items():
        seleccion = selecciones[clave]
        alcanzan = int(pd.to_numeric(
            seleccion.get("socios_captables", pd.Series(dtype=float)), errors="coerce"
        ).ge(capacidad).sum())
        lineas.append(
            f"- {estrategia}: {alcanzan} de {len(seleccion)} alcanzan "
            f"{formato_numero(capacidad)} socios."
        )
    return "\n".join(lineas)


def crear_reporte(
    selecciones,
    evaluacion,
    frecuencias,
    parametros_centrales,
    detalle_sensibilidad=None,
):
    """Genera el resumen ejecutivo de negocio."""
    comparacion = crear_comparacion_estrategias(selecciones)
    nombres_reporte = {
        "Baseline": "Baseline",
        "Modelo A oficial": "Modelo",
        "Alternativa diversificada por clusters": "Alternativa diversificada por clusters",
    }
    comparacion = comparacion.loc[
        comparacion["estrategia"].isin(nombres_reporte)
    ].copy()
    comparacion["estrategia"] = comparacion["estrategia"].replace(nombres_reporte)
    for estrategia, clave in ESTRATEGIAS_REPORTE.items():
        seleccion = selecciones[clave]
        flags = seleccion.get(
            "quality_flag", pd.Series(False, index=seleccion.index)
        ).fillna(False).astype(bool)
        municipios = sorted(
            seleccion.loc[flags, "municipality_name"].astype(str).unique()
        )
        comparacion.loc[
            comparacion["estrategia"].eq(estrategia), "municipios_con_aviso_osm"
        ] = ", ".join(municipios)
    lineas = [
        "# Resumen de resultados de negocio", "",
        "Escenario central: f=2,18; cuota máxima 40%; capacidad 2.600 socios; "
        "coste anual 556.000 EUR. Las cifras son estimaciones, no ingresos observados.", "",
        "## Comparación de estrategias", "", tabla_comparacion_estrategias(comparacion), "",
    ]
    estrategias_cortas = comparacion.loc[
        comparacion["centros_seleccionados"].lt(5), "estrategia"
    ].tolist()
    if estrategias_cortas:
        lineas.extend([
            "Estrategias con menos de cinco centros: " + ", ".join(estrategias_cortas) + ". "
            "Las diferencias de facturación y margen no representan una mejora directa "
            "cuando cambia el número de aperturas.", "",
        ])
    lineas.extend([
        "## Selecciones centrales", "",
        "### Baseline", "", tabla_baseline(selecciones["baseline"]), "",
        "### Modelo", "",
        tabla_seleccion(selecciones["modelo_a"], incluir_diagnosticos=True), "",
        "### Alternativa diversificada por clusters", "",
        tabla_seleccion(
            selecciones["diversificada"], incluir_diagnosticos=True, incluir_motivo=True
        ), "",
        "## Municipios que requieren validación de competencia", "",
        tabla_municipios_validacion(selecciones["pendientes_calidad"]), "",
        "## Indicadores complementarios", "",
        "Socios captables, ratio de capacidad y potencial teórico sirven como "
        "referencia complementaria; no son el resultado principal de la comparación.", "",
        tabla_indicadores_complementarios(selecciones), "",
        "### Referencia operativa", "", nota_tope_capacidad(), "",
        "## Robustez", "",
        "La robustez mide en cuántas de las 108 combinaciones de supuestos aparece cada "
        "municipio entre los seleccionados. Se prueban tres niveles de penetración, tres "
        "de cuota máxima, tres de atractivo, dos juegos de pesos de competencia y dos "
        "reglas de captación. El escenario extremo todo_igual queda excluido. Estas "
        "combinaciones no son probabilidades.", "",
        "La posición media es el puesto medio ocupado solo en los escenarios en los que "
        "el municipio fue seleccionado. La facturación mínima es la estimación más "
        "conservadora entre esos escenarios; no incluye los escenarios en los que no fue "
        "seleccionado. La calidad mostrada corresponde siempre al escenario central.", "",
        tabla_robustez(frecuencias, detalle_sensibilidad), "",
        "## Aportación del clustering", "",
        aporte_clusters(
            selecciones["maxima_facturacion"], selecciones["modelo_a"], evaluacion
        ), "",
        "## Diversificación territorial", "",
        aporte_diversificacion(selecciones["modelo_a"], selecciones["diversificada"]), "",
        resumen_perfiles_clusters(evaluacion, selecciones["diversificada"]), "",
    ])
    return "\n".join(lineas) + "\n"


def mostrar(titulo, tabla):
    """Imprime una tabla para la ejecución CLI."""
    print(f"{titulo}:")
    print(tabla.to_string(index=False))


def _leer_parquet(ruta: Path, prefijo_s3: str) -> pd.DataFrame:
    settings = get_storage_settings()
    if settings.save_locally and ruta.is_file():
        return pd.read_parquet(ruta)

    if settings.save_s3:
        uri = s3_uri_for(ruta.name, prefijo_s3)
        if uri is None:
            raise ValueError(
                f"S3_BUCKET es necesario para leer {ruta.name} desde S3."
            )
        bucket, key = parse_s3_uri(uri)
        client_options = (
            {"region_name": settings.region_name}
            if settings.region_name
            else {}
        )
        try:
            response = boto3.client("s3", **client_options).get_object(
                Bucket=bucket,
                Key=key,
            )
            with response["Body"] as body:
                contents = body.read()
        except (BotoCoreError, ClientError) as error:
            raise RuntimeError(f"No se pudo leer {uri} desde S3.") from error
        return pd.read_parquet(io.BytesIO(contents))

    if settings.save_locally:
        raise FileNotFoundError(
            f"No se encuentra {ruta}; ejecuta antes 02_calidad y 03_modelo."
        )
    raise RuntimeError(
        "No se puede cargar Gold y clusters: activa SAVE_LOCALLY o SAVE_S3."
    )


def validar_codigos(df: pd.DataFrame, fuente: str) -> None:
    codes = df["municipality_code"].astype("string")
    if codes.empty:
        raise ValueError(f"{fuente}: no hay municipios para procesar.")
    if not codes.str.fullmatch(r"\d{5}").fillna(False).all():
        raise ValueError(f"{fuente}: municipality_code debe tener cinco digitos.")
    if codes.duplicated().any():
        raise ValueError(f"{fuente}: municipality_code duplicado.")
    df["municipality_code"] = codes


def cargar_clusters() -> pd.DataFrame:
    """Load all cluster assignments produced for municipalities in the model."""
    clusters = _leer_parquet(CLUSTER_ASSIGNMENTS_PATH, RESULTS_PREFIX)
    if not {"municipality_code", "cluster"}.issubset(clusters.columns):
        raise ValueError(
            f"{CLUSTER_ASSIGNMENTS_PATH.name} debe tener las columnas "
            "municipality_code y cluster."
        )
    validar_codigos(clusters, CLUSTER_ASSIGNMENTS_PATH.name)
    labels = pd.to_numeric(clusters["cluster"], errors="raise")
    if (
        labels.isna().any()
        or not np.isfinite(labels.astype(float)).all()
        or labels.lt(0).any()
        or labels.mod(1).ne(0).any()
    ):
        raise ValueError(
            f"{CLUSTER_ASSIGNMENTS_PATH.name}: cluster debe ser un entero no negativo."
        )
    clusters["cluster"] = labels.astype("int64")
    print(
        f"Clusters leídos de {CLUSTER_ASSIGNMENTS_PATH.name}: "
        f"{clusters['cluster'].nunique()} grupos"
    )
    return clusters[["municipality_code", "cluster"]]


def cargar():
    df = _leer_parquet(ORO, "gold")
    falta = [c for c in NECESARIAS if c not in df.columns]
    if falta:
        raise ValueError(f"Faltan columnas: {falta}")
    validar_codigos(df, "Gold")
    if "cluster" in df.columns:
        raise ValueError("Gold no debe contener cluster; se lee de la salida del modelo.")
    for column in ["population_18_50", "gyms_count", "other_sports_facilities_count"]:
        values = pd.to_numeric(df[column], errors="raise")
        if (values.isna().any() or not np.isfinite(values.astype(float)).all()
                or values.lt(0).any() or values.mod(1).ne(0).any()):
            raise ValueError(f"Gold: {column} debe contener enteros no negativos.")
        df[column] = values
    if df["population_18_50"].eq(0).any():
        raise ValueError("Gold: population_18_50 debe ser positiva.")
    clusters = cargar_clusters()
    gold_codes = set(df["municipality_code"])
    cluster_codes = set(clusters["municipality_code"])
    absent_from_gold = cluster_codes - gold_codes
    if absent_from_gold:
        raise ValueError(
            "Hay asignaciones de cluster para códigos que no existen en Gold: "
            + ", ".join(sorted(absent_from_gold))
        )

    gold_count = len(df)
    df = df.loc[df["municipality_code"].isin(cluster_codes)].copy()
    df = df.merge(
        clusters,
        on="municipality_code",
        how="inner",
        validate="one_to_one",
    )
    print(
        f"Entrada: Gold {gold_count} municipios; "
        f"{len(df)} incluidos tras filtros del modelo; clusters: sí"
    )
    return df


def incorporar_calidad_central_en_robustez(frecuencias, evaluacion):
    """Cruza la robustez con el estado de calidad fijo del escenario central."""
    calidad = evaluacion[["municipality_code", "quality_status"]].rename(
        columns={"quality_status": "quality_status_central"}
    )
    return frecuencias.merge(
        calidad, on="municipality_code", how="left", validate="one_to_one"
    )


def validar_resultados_centrales(evaluacion, selecciones, detalle, frecuencias, datos):
    """Aplica invariantes económicas y de selección antes de reemplazar las salidas."""
    numericos = evaluacion.select_dtypes(include=[np.number]).to_numpy(dtype=float)
    if np.isinf(numericos).any():
        raise ValueError("La evaluación central contiene valores infinitos.")
    if (evaluacion["facturacion_sin_tope_capacidad"]
            + 1e-6 < evaluacion["facturacion_anual"]).any():
        raise ValueError("La facturación teórica no puede ser inferior a la facturación con tope.")
    bajo_capacidad = evaluacion["ratio_capacidad"].le(1)
    if not np.allclose(
        evaluacion.loc[bajo_capacidad, "facturacion_sin_tope_capacidad"],
        evaluacion.loc[bajo_capacidad, "facturacion_anual"], rtol=1e-10, atol=1e-6,
    ):
        raise ValueError("Las facturaciones deben coincidir cuando no se alcanza la capacidad.")
    if len(selecciones["baseline"]) != 5:
        raise ValueError("El baseline central debe seleccionar exactamente cinco municipios.")
    if not selecciones["maxima_facturacion"]["viable"].all():
        raise ValueError("La selección de máxima facturación solo puede incluir viables.")
    modelo_a = selecciones["modelo_a"]
    if not (
        modelo_a["candidate_flag"]
        & modelo_a["viable"]
        & modelo_a["quality_flag"]
    ).all():
        raise ValueError(
            "El Modelo solo puede incluir candidatos viables que superan calidad."
        )
    for clave in ("baseline", "maxima_facturacion", "modelo_a", "diversificada"):
        seleccion = selecciones[clave]
        if len(seleccion) > 5:
            raise ValueError("Ninguna estrategia puede seleccionar más de cinco municipios.")
    diversificada = selecciones["diversificada"]
    if diversificada["municipality_code"].duplicated().any():
        raise ValueError("La alternativa diversificada contiene municipios duplicados.")
    if not (
        diversificada["candidate_flag"]
        & diversificada["viable"]
        & diversificada["quality_flag"]
    ).all():
        raise ValueError(
            "La alternativa diversificada exige candidato, viabilidad y calidad."
        )
    recuento_clusters = diversificada["cluster"].value_counts()
    if recuento_clusters.gt(2).any() or recuento_clusters.eq(2).sum() > 1:
        raise ValueError("La alternativa diversificada solo puede repetir un cluster una vez.")
    if np.isinf(evaluacion["colchon_demanda_pct"].to_numpy(dtype=float)).any():
        raise ValueError("El colchón de demanda contiene valores infinitos.")

    flag_esperado = (
        pd.to_numeric(evaluacion["expected_gyms"], errors="coerce").gt(0)
        & evaluacion["weighted_observed_vs_expected_pct"].ge(50)
    )
    if not evaluacion["quality_flag"].eq(flag_esperado).all():
        raise ValueError("quality_flag no coincide con el control ponderado >= 50%.")
    if int(frecuencias["apariciones"].sum()) != len(detalle):
        raise ValueError("La suma de apariciones de sensibilidad no coincide con las plazas elegidas.")


def main():
    SALIDA.mkdir(parents=True, exist_ok=True)
    datos = cargar()
    parametros_centrales = parametros("central")
    evaluacion = evaluar(
        datos, escenario="central", pesos="central", regla="C", con_candidatos=True
    )
    (
        modelo_final,
        pendientes_calidad,
        ranking_modelo_completo,
        sustituciones_calidad,
    ) = seleccionar_modelo_con_calidad(evaluacion, n=5)
    diversificada = top5_diversificado_clusters(evaluacion)
    selecciones = {
        "baseline": top5_baseline(evaluacion),
        "maxima_facturacion": top5_facturacion(evaluacion),
        "modelo_a": modelo_final,
        "diversificada": diversificada,
        "pendientes_calidad": pendientes_calidad,
    }
    detalle, frecuencias = sensibilidad(datos)
    frecuencias = incorporar_calidad_central_en_robustez(frecuencias, evaluacion)
    validar_resultados_centrales(
        evaluacion, selecciones, detalle, frecuencias, datos
    )
    comparacion = crear_comparacion_estrategias(selecciones)
    reporte = crear_reporte(
        selecciones,
        evaluacion,
        frecuencias,
        parametros_centrales,
        detalle_sensibilidad=detalle,
    )

    eliminados = limpiar_salidas_t5()
    if eliminados:
        print("Salidas T5 anteriores reemplazadas:", ", ".join(eliminados))
    archivos = {
        "baseline_central.csv": selecciones["baseline"],
        "top_facturacion_central.csv": selecciones["maxima_facturacion"],
        "seleccion_modelo_central.csv": selecciones["modelo_a"],
        "modelo_pendiente_validacion.csv": selecciones["pendientes_calidad"],
        "ranking_modelo_completo.csv": ranking_modelo_completo,
        "sustituciones_por_calidad.csv": sustituciones_calidad,
        "seleccion_diversificada_clusters_central.csv": selecciones["diversificada"],
        "comparacion_estrategias_central.csv": comparacion,
        "municipios_evaluados_central.csv": evaluacion,
        "sensibilidad_detalle.csv": detalle,
        "sensibilidad_frecuencias.csv": frecuencias,
    }
    for nombre, tabla in archivos.items():
        tabla.to_csv(SALIDA / nombre, index=False, encoding="utf-8-sig")
    ruta_reporte = SALIDA / "resumen_negocio.md"
    ruta_reporte.write_text(reporte, encoding="utf-8")

    mostrar("Comparación de estrategias centrales", comparacion)
    print("Informe legible:", ruta_reporte)
    print("CSV detallados guardados en:", SALIDA)
    return {
        "selecciones": selecciones,
        "comparacion": comparacion,
        "evaluacion": evaluacion,
        "ranking_modelo_completo": ranking_modelo_completo,
        "sustituciones_calidad": sustituciones_calidad,
        "sensibilidad_detalle": detalle,
        "sensibilidad_frecuencias": frecuencias,
        "resumen_path": ruta_reporte,
    }


if __name__ == "__main__":
    main()
