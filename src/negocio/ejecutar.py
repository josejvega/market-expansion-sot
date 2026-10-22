"""
ejecutar.py  -  T5 de principio a fin.
Uso (desde la raíz del repo):  python -m src.negocio.ejecutar

Entrada:
  - data/processed/gold/tabla_oro_municipios_andalucia.parquet
  - data/resultados/clusters.csv (salida del modelo; parquet como alternativa)
Salida (data/outputs/, ignorado por Git):
  - municipios_evaluados_<pesos>.csv, baseline_<pesos>.csv, top_facturacion_<pesos>.csv
  - si hay clusters: seleccion_modelo_<pesos>.csv, comparacion_<pesos>.csv,
    sensibilidad_detalle.csv, sensibilidad_frecuencias.csv
"""
from pathlib import Path
import numpy as np
import pandas as pd

from src.modelo.modelo import CLUSTERS_PATH, EXPECTED_MUNICIPALITIES
from src.procesado.common.paths import DATA_DIR, GOLD_TABLE_PATH

from .supuestos import parametros
from .valor_negocio import (
    evaluar, sensibilidad, top5_baseline, top5_diversificado_clusters,
    top5_facturacion, top5_modelo,
)

ORO = GOLD_TABLE_PATH
CLUSTERS = [CLUSTERS_PATH, CLUSTERS_PATH.with_suffix(".parquet")]
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


def tabla_seleccion(tabla, incluir_diagnosticos=False, incluir_motivo=False):
    """Formatea una estrategia en una tabla Markdown orientada a decisión."""
    encabezados = [
        "Posición", "Municipio", "Cluster", "Población 18-50", "Competidores ponderados",
        "Socios captables sin tope",
        "Potencial teórico sin límite de capacidad (EUR)", "Ratio de capacidad",
    ]
    if incluir_diagnosticos:
        encabezados.extend([
            "Competencia por 10.000", "Media de competencia del cluster",
            "Colchón de demanda",
        ])
    encabezados.extend([
        "Facturación anual con tope (EUR)", "Margen anual (EUR)", "Aviso OSM",
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
            formato_numero(fila["socios_captables"], 0),
            formato_numero(fila["facturacion_sin_tope_capacidad"], 0),
            formato_con_sufijo(fila["ratio_capacidad"], 2, "×"),
        ]
        if incluir_diagnosticos:
            valores.extend([
                formato_numero(fila["comp_per_10k_18_50"], 2),
                formato_numero(fila["media_cluster_comp_per_10k"], 2),
                formato_con_sufijo(fila["colchon_demanda_pct"] * 100, 1, "%"),
            ])
        aviso = fila.get("aviso_calidad", "")
        valores.extend([
            formato_numero(fila["facturacion_anual"]),
            formato_numero(fila["margen_eur"]),
            "" if pd.isna(aviso) else aviso,
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
        "Margen anual (EUR)", "Viable", "Aviso OSM",
    ]
    filas = []
    for posicion, (_, fila) in enumerate(tabla.iterrows(), start=1):
        aviso = fila.get("aviso_calidad", "")
        filas.append([
            formato_numero(posicion), fila["municipality_name"],
            formato_numero(fila.get("cluster", np.nan)),
            formato_numero(fila["population_18_50"]),
            formato_numero(fila["competidores_pond"], 1),
            formato_numero(fila["facturacion_anual"]),
            formato_numero(fila["margen_eur"]),
            "Sí" if fila["viable"] else "No",
            "" if pd.isna(aviso) else aviso,
        ])
    if not filas:
        filas = [["—"] * len(encabezados)]
    return tabla_markdown(encabezados, filas)


def resumir_estrategia(nombre, seleccion):
    """Calcula las métricas comparables de una selección de centros."""
    avisos = seleccion.get("aviso_calidad", pd.Series("", index=seleccion.index))
    avisos = avisos.fillna("").astype(str).str.strip().ne("")
    nombres_aviso = sorted(seleccion.loc[avisos, "municipality_name"].astype(str).unique())
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
        "Demanda media por competidor", "Municipios con aviso OSM", "Clusters representados",
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


def tabla_robustez(frecuencias):
    encabezados = [
        "Municipio", "Apariciones", "Posición media", "Facturación mínima (EUR)",
        "Facturación máxima (EUR)", "Robustez", "Aviso OSM",
    ]
    filas = [[
        fila.municipality_name,
        formato_numero(fila.apariciones),
        formato_numero(fila.posicion_media, 1),
        formato_numero(fila.fact_min),
        formato_numero(fila.fact_max),
        fila.robustez,
        "" if pd.isna(fila.aviso_calidad) else fila.aviso_calidad,
    ] for fila in frecuencias.head(10).itertuples(index=False)]
    if not filas:
        filas = [["—"] * len(encabezados)]
    return tabla_markdown(encabezados, filas)


def nota_tope_capacidad():
    return (
        "El potencial teórico sin límite de capacidad es una métrica diagnóstica y no "
        "representa ingresos realizables con un único club de 2.600 socios."
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
        f"Modelo A representa {clusters_modelo} {etiqueta_clusters_modelo} y la alternativa "
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


def crear_reporte(selecciones, evaluacion, frecuencias, parametros_centrales):
    """Genera el informe central con seis tablas y narrativas comparativas."""
    comparacion = crear_comparacion_estrategias(selecciones)
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
        "### Baseline obligatorio", "", tabla_baseline(selecciones["baseline"]), "",
        "### Máxima facturación sin clusters", "",
        tabla_seleccion(selecciones["maxima_facturacion"]), "",
        "### Modelo A oficial", "",
        tabla_seleccion(selecciones["modelo_a"], incluir_diagnosticos=True), "",
        "### Alternativa diversificada por clusters", "",
        tabla_seleccion(
            selecciones["diversificada"], incluir_diagnosticos=True, incluir_motivo=True
        ), "",
        nota_tope_capacidad(), "",
        "## Robustez", "",
        "Las apariciones cuentan combinaciones de supuestos, no son probabilidades.", "",
        tabla_robustez(frecuencias), "",
        "## Aportación del clustering", "",
        aporte_clusters(
            selecciones["maxima_facturacion"], selecciones["modelo_a"], evaluacion
        ), "",
        "## Diversificación territorial", "",
        aporte_diversificacion(selecciones["modelo_a"], selecciones["diversificada"]), "",
        resumen_perfiles_clusters(evaluacion, selecciones["diversificada"]), "",
        "## Validaciones pendientes antes de recomendar inversión", "",
        validaciones_osm(selecciones), "",
        "## Límite de capacidad", "",
        "Centros seleccionados que alcanzan el tope de capacidad:",
        resumen_capacidad(selecciones, parametros_centrales["capacidad"]), "",
        "El potencial teórico sin límite de capacidad se usa únicamente para diferenciar "
        "municipios con demanda excedente.",
    ])
    return "\n".join(lineas) + "\n"


def mostrar(titulo, tabla):
    """Imprime una tabla para la ejecución CLI."""
    print(f"{titulo}:")
    print(tabla.to_string(index=False))


def validar_codigos(df: pd.DataFrame, fuente: str) -> None:
    codes = df["municipality_code"].astype("string")
    if len(codes) != EXPECTED_MUNICIPALITIES:
        raise ValueError(f"{fuente}: se esperaban {EXPECTED_MUNICIPALITIES} municipios.")
    if not codes.str.fullmatch(r"\d{5}").fillna(False).all():
        raise ValueError(f"{fuente}: municipality_code debe tener cinco digitos.")
    if codes.duplicated().any():
        raise ValueError(f"{fuente}: municipality_code duplicado.")
    df["municipality_code"] = codes


def cargar_clusters() -> pd.DataFrame:
    """Lee primero el CSV producido por el modelo y exige cobertura completa."""
    for ruta in CLUSTERS:
        if ruta.exists():
            cl = (pd.read_parquet(ruta) if ruta.suffix == ".parquet"
                  else pd.read_csv(ruta, dtype={"municipality_code": "string"}))
            if not {"municipality_code", "cluster"}.issubset(cl.columns):
                raise ValueError(f"{ruta.name} debe tener las columnas municipality_code y cluster.")
            validar_codigos(cl, ruta.name)
            labels = pd.to_numeric(cl["cluster"], errors="raise")
            if (labels.isna().any() or not np.isfinite(labels.astype(float)).all()
                    or labels.lt(0).any() or labels.mod(1).ne(0).any()):
                raise ValueError(f"{ruta.name}: cluster debe ser un entero no negativo.")
            cl["cluster"] = labels.astype("int64")
            print(f"Clusters leídos de {ruta.name}: {cl['cluster'].nunique()} grupos")
            return cl[["municipality_code", "cluster"]]
    raise FileNotFoundError(
        f"No se encuentran clusters en {CLUSTERS}. Ejecuta python -m src.modelo.modelo."
    )


def cargar():
    if not ORO.is_file():
        raise FileNotFoundError(f"No se encuentra Gold en {ORO}. Ejecuta primero 02_calidad.")
    df = pd.read_parquet(ORO)
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
    cl = cargar_clusters()
    if set(df["municipality_code"]) != set(cl["municipality_code"]):
        raise ValueError("Los clusters deben cubrir exactamente los municipios de Gold.")
    df = df.merge(cl, on="municipality_code", how="left", validate="one_to_one")
    print(f"Entrada: {ORO} · {len(df)} municipios · clusters: sí")
    return df


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
    if not (modelo_a["candidate_flag"] & modelo_a["viable"]).all():
        raise ValueError("Modelo A solo puede incluir candidatos viables.")
    for seleccion in selecciones.values():
        if len(seleccion) > 5:
            raise ValueError("Ninguna estrategia puede seleccionar más de cinco municipios.")
    diversificada = selecciones["diversificada"]
    if diversificada["municipality_code"].duplicated().any():
        raise ValueError("La alternativa diversificada contiene municipios duplicados.")
    if not (diversificada["candidate_flag"] & diversificada["viable"]).all():
        raise ValueError("La alternativa diversificada solo puede incluir candidatos viables.")
    recuento_clusters = diversificada["cluster"].value_counts()
    if recuento_clusters.gt(2).any() or recuento_clusters.eq(2).sum() > 1:
        raise ValueError("La alternativa diversificada solo puede repetir un cluster una vez.")
    if np.isinf(evaluacion["colchon_demanda_pct"].to_numpy(dtype=float)).any():
        raise ValueError("El colchón de demanda contiene valores infinitos.")

    gimnasios = datos["gyms_count"]
    avisos_esperados = np.where(
        gimnasios.eq(0) & datos["population_18_50"].ge(20_000),
        "Sin gimnasios en OSM: validar con una segunda fuente", "",
    )
    if not evaluacion["aviso_calidad"].eq(avisos_esperados).all():
        raise ValueError("Los avisos OSM no cumplen las condiciones de población y recuento.")
    if int(frecuencias["apariciones"].sum()) != len(detalle):
        raise ValueError("La suma de apariciones de sensibilidad no coincide con las plazas elegidas.")


def main():
    SALIDA.mkdir(parents=True, exist_ok=True)
    datos = cargar()
    parametros_centrales = parametros("central")
    evaluacion = evaluar(
        datos, escenario="central", pesos="central", regla="C", con_candidatos=True
    )
    diversificada = top5_diversificado_clusters(evaluacion)
    selecciones = {
        "baseline": top5_baseline(evaluacion),
        "maxima_facturacion": top5_facturacion(evaluacion),
        "modelo_a": top5_modelo(evaluacion),
        "diversificada": diversificada,
    }
    detalle, frecuencias = sensibilidad(datos)
    validar_resultados_centrales(
        evaluacion, selecciones, detalle, frecuencias, datos
    )
    comparacion = crear_comparacion_estrategias(selecciones)
    reporte = crear_reporte(selecciones, evaluacion, frecuencias, parametros_centrales)

    eliminados = limpiar_salidas_t5()
    if eliminados:
        print("Salidas T5 anteriores reemplazadas:", ", ".join(eliminados))
    archivos = {
        "baseline_central.csv": selecciones["baseline"],
        "top_facturacion_central.csv": selecciones["maxima_facturacion"],
        "seleccion_modelo_central.csv": selecciones["modelo_a"],
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
        "sensibilidad_detalle": detalle,
        "sensibilidad_frecuencias": frecuencias,
        "resumen_path": ruta_reporte,
    }


if __name__ == "__main__":
    main()
