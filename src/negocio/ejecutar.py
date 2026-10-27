"""
ejecutar.py - Negocio (T5) de principio a fin.

Uso (desde la raíz del repositorio):
    python -m src.negocio.ejecutar

Entrada:
    - Tabla Gold municipal.
    - Asignaciones de cluster generadas por el modelo.

Salida (según SAVE_LOCALLY / SAVE_S3):
  - Local: data/outputs/ (ignorada por Git).
  - S3: results/negocio/
Archivos:
    - baseline_central.csv
    - seleccion_modelo_central.csv
    - modelo_pendiente_validacion.csv
    - ranking_modelo_completo.csv
    - sustituciones_por_calidad.csv
    - seleccion_diversificada_clusters_central.csv
    - comparacion_estrategias_central.csv
    - municipios_evaluados_central.csv
    - sensibilidad_detalle.csv
    - sensibilidad_frecuencias.csv
    - tablas_definitivas_negocio.md
"""
import io
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Union

import boto3
import numpy as np
import pandas as pd
from botocore.exceptions import BotoCoreError, ClientError

from src.common.storage import get_storage_settings, s3_uri_for
from src.common.upload_to_s3 import parse_s3_uri, upload_files_to_s3
from src.modelo.modelo import CLUSTER_ASSIGNMENTS_PATH, RESULTS_PREFIX
from src.procesado.common.paths import DATA_DIR, GOLD_TABLE_PATH

from .supuestos import parametros
from .valor_negocio import (
    evaluar,
    seleccionar_modelo_con_calidad,
    sensibilidad,
    top5_baseline,
    top5_diversificado_clusters,
)


ORO = GOLD_TABLE_PATH
SALIDA = DATA_DIR / "outputs"
BUSINESS_RESULTS_PREFIX = "results/negocio"
NOMBRE_INFORME = "tablas_definitivas_negocio.md"

# Archivos que versiones anteriores publicaban en S3 y que ya no se generan.
# Se borran de results/negocio/ para que no queden resultados obsoletos.
SALIDAS_S3_OBSOLETAS = ("resumen_negocio.md", "top_facturacion_central.csv")

NECESARIAS = [
    "municipality_code",
    "municipality_name",
    "population_18_50",
    "gyms_count",
    "other_sports_facilities_count",
]

ESTRATEGIAS = {
    "Baseline": "baseline",
    "Modelo": "modelo",
    "Modelo diversificado por clusters": "diversificada",
}

# Salidas actuales y antiguas que T5 gestiona. Se eliminan antes de escribir
# para no mezclar resultados obsoletos con los nuevos.
ESCENARIOS_ANTERIORES = ("solo_gimnasios", "central", "todo_igual")
PREFIJOS_ANTERIORES = (
    "municipios_evaluados",
    "baseline",
    "top_facturacion",
    "seleccion_modelo",
    "comparacion",
)
ARCHIVOS_T5_GESTIONADOS = {
    f"{prefijo}_{escenario}.csv"
    for prefijo in PREFIJOS_ANTERIORES
    for escenario in ESCENARIOS_ANTERIORES
} | {
    "municipios_evaluados_variantes_central.csv",
    "seleccion_modelo_variantes_central.csv",
    "comparacion_variantes_central.csv",
    "modelo_pendiente_validacion.csv",
    "ranking_modelo_completo.csv",
    "sustituciones_por_calidad.csv",
    "seleccion_diversificada_clusters_central.csv",
    "comparacion_estrategias_central.csv",
    "sensibilidad_detalle.csv",
    "sensibilidad_frecuencias.csv",
    "resumen_negocio.md",
    "tablas_definitivas_negocio.md",
}


# ============================================================
# FORMATO
# ============================================================

def formato_numero(valor, decimales=0):
    """Formatea cifras en estilo español: 2.649.735 o 2.208,9."""
    if valor is None or pd.isna(valor):
        return "—"
    texto = f"{float(valor):,.{decimales}f}"
    return texto.replace(",", "\0").replace(".", ",").replace("\0", ".")


def fmt_entero(valor):
    return formato_numero(valor, 0)


def fmt_dec1(valor):
    return formato_numero(valor, 1)


def fmt_dec2(valor):
    return formato_numero(valor, 2)


def fmt_eur(valor):
    texto = formato_numero(valor, 0)
    return texto if texto == "—" else f"{texto} €"


def fmt_pct(valor):
    texto = formato_numero(valor, 1)
    return texto if texto == "—" else f"{texto} %"


def fmt_pct_fraccion(valor):
    """Convierte 0,314 en 31,4 %."""
    if valor is None or pd.isna(valor):
        return "—"
    return fmt_pct(float(valor) * 100)


def fmt_ratio(valor):
    texto = formato_numero(valor, 2)
    return texto if texto == "—" else f"{texto}×"


def fmt_bool(valor):
    if valor is None or pd.isna(valor):
        return "—"
    if isinstance(valor, str):
        valor = valor.strip().lower() in {"true", "1", "sí", "si", "yes"}
    return "Sí" if bool(valor) else "No"


def fmt_texto(valor):
    if valor is None or pd.isna(valor) or str(valor).strip() == "":
        return "—"
    return str(valor)


def tabla_markdown(encabezados, filas):
    """Construye una tabla Markdown sin dependencias externas."""
    if not filas:
        filas = [["—"] * len(encabezados)]
    filas = [
        [str(valor).replace("|", "\\|").replace("\n", " ") for valor in fila]
        for fila in filas
    ]
    lineas = [
        "| " + " | ".join(encabezados) + " |",
        "| " + " | ".join(["---"] * len(encabezados)) + " |",
    ]
    lineas.extend("| " + " | ".join(fila) + " |" for fila in filas)
    return "\n".join(lineas)


def tabla_desde_df(df, especificacion, quitar_constantes=False):
    """
    Convierte un DataFrame en tabla Markdown.

    especificacion: lista de (columna, encabezado, formato).
    Si quitar_constantes=True y una columna tiene el mismo valor en todas
    las filas, se elimina de la tabla y se devuelve como nota aparte.
    """
    if df is None or df.empty:
        return "_Sin resultados._", []

    columnas = [item for item in especificacion if item[0] in df.columns]
    notas = []

    if quitar_constantes and len(df) > 1:
        conservadas = []
        for columna, encabezado, formato in columnas:
            valores = df[columna].map(formato)
            if valores.nunique(dropna=False) == 1 and columna != "municipality_name":
                notas.append(f"**{encabezado}:** {valores.iloc[0]} en todos los municipios.")
            else:
                conservadas.append((columna, encabezado, formato))
        columnas = conservadas

    encabezados = [encabezado for _, encabezado, _ in columnas]
    filas = [
        [formato(fila[columna]) for columna, _, formato in columnas]
        for _, fila in df.iterrows()
    ]
    return tabla_markdown(encabezados, filas), notas


# ============================================================
# LIMPIEZA DE SALIDAS
# ============================================================

def limpiar_salidas_t5(directorio=SALIDA):
    """Elimina únicamente los archivos conocidos y gestionados por T5."""
    if not directorio.exists():
        return []
    eliminados = []
    for nombre in sorted(ARCHIVOS_T5_GESTIONADOS):
        ruta = directorio / nombre
        if ruta.is_file():
            ruta.unlink()
            eliminados.append(nombre)
    return eliminados


def limpiar_salidas_obsoletas_s3():
    """Borra de S3 los archivos que versiones anteriores publicaban y ya no se generan."""
    settings = get_storage_settings()
    if not settings.save_s3 or not settings.bucket_name:
        return []
    client_options = {"region_name": settings.region_name} if settings.region_name else {}
    eliminados = []
    try:
        client = boto3.client("s3", **client_options)
        for nombre in SALIDAS_S3_OBSOLETAS:
            key = f"{BUSINESS_RESULTS_PREFIX}/{nombre}"
            client.delete_object(Bucket=settings.bucket_name, Key=key)
            eliminados.append(key)
    except (BotoCoreError, ClientError) as error:
        print(f"Aviso: no se pudieron borrar salidas obsoletas de S3 ({error}).")
    return eliminados


def guardar_salidas_negocio(
    archivos: dict[str, pd.DataFrame],
    informe: str,
    directorio: Path = SALIDA,
) -> dict[str, Union[Path, str]]:
    """Guarda las tablas CSV y el informe Markdown en local, en S3 o en ambos."""
    if not archivos:
        raise ValueError("Debe proporcionarse al menos una tabla de negocio.")
    if NOMBRE_INFORME in archivos:
        raise ValueError(f"'{NOMBRE_INFORME}' está reservado para el informe.")
    nombres = [*archivos, NOMBRE_INFORME]
    if any(Path(nombre).name != nombre for nombre in nombres):
        raise ValueError("Los nombres de salida deben ser nombres de archivo.")

    settings = get_storage_settings()
    if not settings.save_locally and not settings.save_s3:
        raise RuntimeError("Las salidas de negocio requieren SAVE_LOCALLY o SAVE_S3.")

    def escribir_salidas(directorio_salida: Path) -> list[Path]:
        directorio_salida.mkdir(parents=True, exist_ok=True)
        paths = []
        for nombre, tabla in archivos.items():
            ruta = directorio_salida / nombre
            tabla.to_csv(ruta, index=False, encoding="utf-8-sig")
            paths.append(ruta)
        ruta_informe = directorio_salida / NOMBRE_INFORME
        ruta_informe.write_text(informe, encoding="utf-8")
        paths.append(ruta_informe)
        return paths

    if settings.save_locally:
        directorio = Path(directorio)
        eliminados = limpiar_salidas_t5(directorio)
        if eliminados:
            print("Salidas T5 anteriores reemplazadas:", ", ".join(eliminados))
        paths = escribir_salidas(directorio)
    else:
        with TemporaryDirectory(prefix="market-expansion-business-") as directory:
            paths = escribir_salidas(Path(directory))
            uploaded_uris = upload_files_to_s3(
                paths,
                prefix=BUSINESS_RESULTS_PREFIX,
                bucket_name=settings.bucket_name,
                region_name=settings.region_name,
            )
        return dict(zip(nombres, uploaded_uris))

    if settings.save_s3:
        upload_files_to_s3(
            paths,
            prefix=BUSINESS_RESULTS_PREFIX,
            bucket_name=settings.bucket_name,
            region_name=settings.region_name,
        )
    return {path.name: path for path in paths}


# ============================================================
# MÉTRICAS DE ESTRATEGIA
# ============================================================

def resumir_estrategia(nombre, seleccion):
    """Calcula los KPI comparables de una estrategia."""

    def suma(columna):
        if seleccion.empty or columna not in seleccion:
            return 0.0
        return float(pd.to_numeric(seleccion[columna], errors="coerce").sum())

    def media(columna):
        if seleccion.empty or columna not in seleccion:
            return np.nan
        return float(pd.to_numeric(seleccion[columna], errors="coerce").mean())

    return {
        "estrategia": nombre,
        "centros_seleccionados": len(seleccion),
        "centros_viables": (
            int(seleccion["viable"].fillna(False).astype(bool).sum())
            if "viable" in seleccion else 0
        ),
        "facturacion_operativa_total_eur": suma("facturacion_anual"),
        "coste_anual_escalado_total_eur": suma("coste_anual_escalado"),
        "margen_operativo_total_eur": suma("margen_eur"),
        "perdidas_operativas_totales_eur": suma("perdidas_eur"),
        "potencial_anual_sin_tope_eur": suma("facturacion_sin_tope_capacidad"),
        "demanda_media_por_competidor": media("demanda_por_comp"),
        "clusters_representados": (
            int(seleccion["cluster"].nunique()) if "cluster" in seleccion else 0
        ),
    }


def crear_comparacion_estrategias(selecciones):
    """Tabla comparativa de Baseline, Modelo y Modelo diversificado."""
    return pd.DataFrame([
        resumir_estrategia(nombre, selecciones[clave])
        for nombre, clave in ESTRATEGIAS.items()
    ])


# ============================================================
# SECCIONES DEL MARKDOWN DE TABLAS DEFINITIVAS
# ============================================================

def seccion_referencia_operativa(parametros_centrales):
    ticket = parametros_centrales["ticket_mensual"]
    capacidad = parametros_centrales["capacidad"]
    coste = parametros_centrales["coste_anual_club"]

    facturacion_referencia = capacidad * ticket * 12
    ingresos_netos_por_socio = ticket * 12 - 0.4 * coste / capacidad
    socios_equilibrio = 0.6 * coste / ingresos_netos_por_socio

    return "\n".join([
        "## Referencia operativa",
        "",
        f"- Coste anual de referencia: {fmt_eur(coste)} para "
        f"{fmt_entero(capacidad)} socios captables.",
        "- Coste escalado por municipio: coste de referencia × "
        "(0,6 + 0,4 × socios captables / capacidad de referencia).",
        f"- Ticket mensual sin IVA: {formato_numero(ticket, 2)} €.",
        f"- Punto de equilibrio aproximado: {fmt_entero(socios_equilibrio)} socios.",
        f"- Capacidad de referencia de un centro estándar: {fmt_entero(capacidad)} socios.",
        f"- Facturación operativa de referencia a capacidad completa: "
        f"{fmt_eur(facturacion_referencia)} al año.",
        "",
        "La capacidad de referencia no es la capacidad óptima calculada para cada "
        "municipio. El coste anual y el margen se estiman con los socios captables "
        "y la facturación sin límite de capacidad. El **potencial anual sin tope** "
        "muestra el valor de la demanda captable; cuando supera ampliamente la "
        "referencia, conviene estudiar un centro mayor o varias aperturas y "
        "recalcular sus costes.",
    ])


def seccion_comparacion(comparacion):
    especificacion = [
        ("estrategia", "Estrategia", fmt_texto),
        ("centros_seleccionados", "Municipios seleccionados", fmt_entero),
        ("centros_viables", "Municipios viables", fmt_entero),
        ("facturacion_operativa_total_eur", "Facturación operativa total", fmt_eur),
        ("coste_anual_escalado_total_eur", "Coste anual escalado total", fmt_eur),
        ("margen_operativo_total_eur", "Margen escalado total", fmt_eur),
        ("perdidas_operativas_totales_eur", "Pérdidas operativas", fmt_eur),
        ("potencial_anual_sin_tope_eur", "Potencial anual sin tope", fmt_eur),
        ("demanda_media_por_competidor", "Demanda media por competidor", fmt_dec1),
        ("clusters_representados", "Clusters representados", fmt_entero),
    ]
    tabla, _ = tabla_desde_df(comparacion, especificacion)
    return "\n".join([
        "## Tabla A. Comparación de estrategias",
        "",
        tabla,
        "",
        "Las tres estrategias se evalúan con las mismas fórmulas económicas.",
    ])


ESPEC_MODELO = [
    ("posicion", "Posición", fmt_entero),
    ("municipality_name", "Municipio", fmt_texto),
    ("cluster", "Cluster", fmt_entero),
    ("population_18_50", "Población 18-50", fmt_entero),
    ("competidores_pond", "Competencia ponderada", fmt_dec1),
    ("comp_per_10k_18_50", "Competencia por 10.000", fmt_dec2),
    ("media_cluster_comp_per_10k", "Media del cluster", fmt_dec2),
    ("socios_captables", "Socios captables", fmt_entero),
    ("facturacion_sin_tope_capacidad", "Potencial anual sin tope", fmt_eur),
    ("coste_anual_escalado", "Coste anual escalado", fmt_eur),
    ("ratio_capacidad", "Ratio de capacidad", fmt_ratio),
    ("facturacion_anual", "Facturación operativa", fmt_eur),
    ("margen_escalado_eur", "Margen escalado", fmt_eur),
    ("colchon_demanda_pct", "Colchón de demanda", fmt_pct_fraccion),
    ("weighted_observed_vs_expected_pct", "Cobertura ponderada", fmt_pct),
    ("quality_status", "Calidad del dato", fmt_texto),
]


def seccion_modelo(modelo):
    tabla, notas = tabla_desde_df(modelo, ESPEC_MODELO, quitar_constantes=True)
    lineas = [
        "## Tabla B. Recomendación final del Modelo",
        "",
        "Municipios candidatos (menos competencia que la media de su cluster), "
        "viables y que superan el control de calidad.",
        "",
        tabla,
    ]
    if notas:
        lineas.extend(["", "Valores comunes a todos los seleccionados:", ""])
        lineas.extend(f"- {nota}" for nota in notas)
    return "\n".join(lineas)


def seccion_pendientes(pendientes):
    especificacion = [
        ("posicion_ranking_precalidad", "Posición económica original", fmt_entero),
        ("municipality_name", "Municipio", fmt_texto),
        ("cluster", "Cluster", fmt_entero),
        ("competidores_pond", "Competencia ponderada", fmt_dec1),
        ("expected_gyms", "Competencia esperada", fmt_dec2),
        ("weighted_observed_vs_expected_pct", "Cobertura ponderada", fmt_pct),
        ("facturacion_sin_tope_capacidad", "Potencial anual sin tope", fmt_eur),
        ("motivo_calidad", "Motivo", fmt_texto),
    ]
    tabla, _ = tabla_desde_df(pendientes, especificacion)
    return "\n".join([
        "## Tabla C. Oportunidades pendientes de validación",
        "",
        "No se eliminan: tienen buena posición económica, pero su competencia "
        "ponderada es inferior al 50 % de la referencia (1 equivalente de gimnasio "
        "por cada 10.000 habitantes de 18 a 50 años). Deben validarse con una "
        "segunda fuente antes de recomendar inversión.",
        "",
        tabla,
    ])


def seccion_sustituciones(sustituciones):
    especificacion = [
        ("posicion_original", "Posición original", fmt_entero),
        ("municipality_name_descartado", "Municipio pendiente de validar", fmt_texto),
        ("municipality_name_sustituto", "Municipio que ocupa su plaza", fmt_texto),
    ]
    if sustituciones is None or sustituciones.empty:
        cuerpo = "No fue necesario sustituir municipios por calidad."
    else:
        cuerpo, _ = tabla_desde_df(sustituciones, especificacion)
    return "\n".join([
        "## Tabla D. Sustituciones por calidad",
        "",
        cuerpo,
    ])


def seccion_diversificada(diversificada, evaluacion):
    especificacion = ESPEC_MODELO + [
        ("motivo_seleccion", "Motivo de selección", fmt_texto),
    ]
    tabla, notas = tabla_desde_df(diversificada, especificacion, quitar_constantes=True)

    datos = evaluacion.copy()
    for columna in ("candidate_flag", "viable", "quality_flag"):
        datos[columna] = datos[columna].fillna(False).astype(bool)
    datos["candidato_viable"] = datos["candidate_flag"] & datos["viable"]
    datos["valido"] = datos["candidato_viable"] & datos["quality_flag"]

    diagnostico = datos.groupby("cluster").agg(
        municipios=("municipality_code", "size"),
        candidatos=("candidate_flag", "sum"),
        viables=("viable", "sum"),
        candidatos_viables=("candidato_viable", "sum"),
        validos=("valido", "sum"),
    ).reset_index()

    tabla_diag, _ = tabla_desde_df(diagnostico, [
        ("cluster", "Cluster", fmt_entero),
        ("municipios", "Municipios", fmt_entero),
        ("candidatos", "Candidatos", fmt_entero),
        ("viables", "Viables", fmt_entero),
        ("candidatos_viables", "Candidatos viables", fmt_entero),
        ("validos", "Candidatos viables con calidad", fmt_entero),
    ])

    sin_validos = diagnostico.loc[diagnostico["validos"].eq(0), "cluster"].tolist()

    lineas = [
        "## Tabla E. Modelo diversificado por clusters",
        "",
        "Alternativa de cartera: intenta representar distintos perfiles municipales "
        "sin incluir municipios no viables o con calidad insuficiente. No es una "
        "obligación del challenge ni una mejora automática frente al Modelo.",
        "",
        tabla,
    ]
    if notas:
        lineas.extend(["", "Valores comunes a todos los seleccionados:", ""])
        lineas.extend(f"- {nota}" for nota in notas)

    lineas.extend([
        "",
        "### Por qué algunos clusters no aportan municipios",
        "",
        tabla_diag,
        "",
    ])
    if sin_validos:
        lineas.append(
            "Los clusters "
            + ", ".join(fmt_entero(c) for c in sin_validos)
            + " no tienen ningún municipio que sea a la vez candidato, viable y con "
            "calidad suficiente. Son municipios con poca población objetivo: aunque "
            "tengan poca competencia, la demanda captable no alcanza el punto de "
            "equilibrio de un centro estándar. Por eso no se fuerzan cinco plazas."
        )
    else:
        lineas.append(
            "Todos los clusters tienen al menos un municipio candidato, viable y "
            "con calidad suficiente."
        )
    return "\n".join(lineas)


def seccion_baseline(baseline):
    especificacion = [
        ("municipality_name", "Municipio", fmt_texto),
        ("cluster", "Cluster", fmt_entero),
        ("population_18_50", "Población 18-50", fmt_entero),
        ("competidores_pond", "Competencia ponderada", fmt_dec1),
        ("candidate_flag", "Es candidato", fmt_bool),
        ("viable", "Es viable", fmt_bool),
        ("quality_flag", "Supera calidad", fmt_bool),
        ("facturacion_anual", "Facturación operativa", fmt_eur),
        ("facturacion_sin_tope_capacidad", "Potencial anual sin tope", fmt_eur),
        ("coste_anual_escalado", "Coste anual escalado", fmt_eur),
        ("margen_escalado_eur", "Margen escalado", fmt_eur),
        ("weighted_observed_vs_expected_pct", "Cobertura ponderada", fmt_pct),
    ]
    tabla, _ = tabla_desde_df(baseline, especificacion)
    return "\n".join([
        "## Tabla F. Baseline y diagnóstico",
        "",
        "El baseline representa la práctica simple del cliente: abrir en los cinco "
        "municipios con mayor población de 18 a 50 años, sin tener en cuenta "
        "competencia, viabilidad ni calidad del dato.",
        "",
        tabla,
        "",
        "Una cobertura ponderada superior al 100 % indica que la oferta ponderada "
        "observada supera la referencia utilizada. No demuestra por sí sola "
        "sobresaturación ni un error del dato.",
    ])


def seccion_robustez(frecuencias):
    especificacion = [
        ("municipality_name", "Municipio", fmt_texto),
        ("robustez", "Robustez", fmt_texto),
        ("posicion_media", "Posición media cuando aparece", fmt_dec1),
        ("fact_min", "Facturación mínima cuando aparece", fmt_eur),
        ("quality_status_central", "Calidad en el escenario central", fmt_texto),
    ]
    total = (
        int(frecuencias["combinaciones_totales"].max())
        if "combinaciones_totales" in frecuencias and not frecuencias.empty
        else 108
    )
    tabla, _ = tabla_desde_df(frecuencias.head(10), especificacion)
    return "\n".join([
        "## Tabla G. Robustez",
        "",
        f"La sensibilidad repite la selección del Modelo en {total} combinaciones de "
        "supuestos: 3 niveles de penetración × 3 de cuota máxima × 3 de atractivo × "
        "2 juegos de pesos de competencia × 2 reglas de captación. El escenario "
        "extremo `todo_igual` queda excluido.",
        "",
        "- **Robustez:** número de combinaciones en las que el municipio aparece "
        "entre los seleccionados. No es una probabilidad.",
        "- **Posición media cuando aparece:** puesto medio ocupado solo en esas combinaciones.",
        "- **Facturación mínima cuando aparece:** estimación más conservadora entre "
        "las combinaciones donde sí fue seleccionado.",
        "- **Calidad:** estado calculado con los pesos del escenario central.",
        "",
        tabla,
    ])


def seccion_conclusion(comparacion, modelo, sustituciones):
    base = comparacion.set_index("estrategia").loc["Baseline"]
    mod = comparacion.set_index("estrategia").loc["Modelo"]

    diferencia_margen = mod["margen_operativo_total_eur"] - base["margen_operativo_total_eur"]
    recomendados = ", ".join(modelo["municipality_name"].astype(str)) or "ninguno"
    sustituidos = (
        ", ".join(sustituciones["municipality_name_descartado"].astype(str))
        if sustituciones is not None and not sustituciones.empty
        else "ninguno"
    )

    return "\n".join([
        "## Conclusión: por qué el Modelo mejora el baseline",
        "",
        f"- **Recomendación del Modelo:** {recomendados}.",
        f"- **Viabilidad:** el Modelo selecciona {fmt_entero(mod['centros_viables'])} "
        f"municipios viables de {fmt_entero(mod['centros_seleccionados'])}, frente a "
        f"{fmt_entero(base['centros_viables'])} de "
        f"{fmt_entero(base['centros_seleccionados'])} en el baseline.",
        f"- **Margen escalado total:** {fmt_eur(mod['margen_operativo_total_eur'])} "
        f"frente a {fmt_eur(base['margen_operativo_total_eur'])} "
        f"(diferencia de {fmt_eur(diferencia_margen)}).",
        f"- **Pérdidas evitadas:** el baseline acumula "
        f"{fmt_eur(base['perdidas_operativas_totales_eur'])} de pérdidas; el Modelo, "
        f"{fmt_eur(mod['perdidas_operativas_totales_eur'])}.",
        f"- **Competencia:** demanda media por competidor de "
        f"{fmt_dec1(mod['demanda_media_por_competidor'])} en el Modelo frente a "
        f"{fmt_dec1(base['demanda_media_por_competidor'])} en el baseline.",
        f"- **Calidad:** municipios sustituidos por calidad insuficiente: {sustituidos}.",
        "",
        "El baseline prioriza el tamaño del mercado. El Modelo añade competencia "
        "relativa frente a municipios comparables, viabilidad económica y un control "
        "mínimo de calidad del dato.",
        "",
        "**Nivel de confianza: medio.** Población, renta y cálculos son reproducibles, "
        "pero la competencia procede de OpenStreetMap, con cobertura desigual. Antes de "
        "invertir deben validarse competencia real, ubicación concreta, costes locales, "
        "inversión inicial y ritmo de maduración del centro.",
    ])


def crear_tablas_definitivas_md(
    selecciones,
    comparacion,
    evaluacion,
    frecuencias,
    sustituciones_calidad,
    parametros_centrales,
):
    """Genera el único Markdown con las tablas definitivas de negocio."""
    secciones = [
        "# Tablas definitivas de negocio",
        "",
        "Escenario central. Las cifras son estimaciones, no ingresos observados.",
        "",
        seccion_referencia_operativa(parametros_centrales),
        seccion_comparacion(comparacion),
        seccion_modelo(selecciones["modelo"]),
        seccion_pendientes(selecciones["pendientes_calidad"]),
        seccion_sustituciones(sustituciones_calidad),
        seccion_diversificada(selecciones["diversificada"], evaluacion),
        seccion_baseline(selecciones["baseline"]),
        seccion_robustez(frecuencias),
        seccion_conclusion(comparacion, selecciones["modelo"], sustituciones_calidad),
    ]
    return "\n\n".join(secciones) + "\n"


# ============================================================
# CARGA DE DATOS
# ============================================================

def mostrar(titulo, tabla):
    """Imprime una tabla en la terminal sin notación científica."""
    print(f"{titulo}:")
    with pd.option_context(
        "display.float_format", lambda valor: formato_numero(valor, 1),
        "display.max_columns", None,
        "display.width", 250,
    ):
        print(tabla.to_string(index=False))


def _leer_parquet(ruta: Path, prefijo_s3: str) -> pd.DataFrame:
    settings = get_storage_settings()
    if settings.save_locally and ruta.is_file():
        return pd.read_parquet(ruta)
    if settings.save_s3:
        uri = s3_uri_for(ruta.name, prefijo_s3)
        if uri is None:
            raise ValueError(f"S3_BUCKET es necesario para leer {ruta.name} desde S3.")
        bucket, key = parse_s3_uri(uri)
        client_options = (
            {"region_name": settings.region_name} if settings.region_name else {}
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
    raise RuntimeError("No se puede cargar Gold y clusters: activa SAVE_LOCALLY o SAVE_S3.")


def validar_codigos(df: pd.DataFrame, fuente: str) -> None:
    codes = df["municipality_code"].astype("string")
    if codes.empty:
        raise ValueError(f"{fuente}: no hay municipios para procesar.")
    if not codes.str.fullmatch(r"\d{5}").fillna(False).all():
        raise ValueError(f"{fuente}: municipality_code debe tener cinco dígitos.")
    if codes.duplicated().any():
        raise ValueError(f"{fuente}: municipality_code duplicado.")
    df["municipality_code"] = codes


def cargar_clusters() -> pd.DataFrame:
    """Lee las asignaciones de cluster generadas por el modelo."""
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
        if (
            values.isna().any()
            or not np.isfinite(values.astype(float)).all()
            or values.lt(0).any()
            or values.mod(1).ne(0).any()
        ):
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
    df = df.merge(clusters, on="municipality_code", how="inner", validate="one_to_one")
    print(
        f"Entrada: Gold {gold_count} municipios; "
        f"{len(df)} incluidos tras filtros del modelo; clusters: sí"
    )
    return df


# ============================================================
# VALIDACIONES
# ============================================================

def incorporar_calidad_central_en_robustez(frecuencias, evaluacion):
    """Cruza la robustez con el estado de calidad del escenario central."""
    calidad = evaluacion[["municipality_code", "quality_status"]].rename(
        columns={"quality_status": "quality_status_central"}
    )
    return frecuencias.merge(
        calidad, on="municipality_code", how="left", validate="one_to_one"
    )


def validar_resultados_centrales(evaluacion, selecciones, detalle, frecuencias):
    """Comprueba invariantes económicas y de selección antes de escribir salidas."""
    numericos = evaluacion.select_dtypes(include=[np.number]).to_numpy(dtype=float)
    if np.isinf(numericos).any():
        raise ValueError("La evaluación central contiene valores infinitos.")

    if (
        evaluacion["facturacion_sin_tope_capacidad"] + 1e-6
        < evaluacion["facturacion_anual"]
    ).any():
        raise ValueError("El potencial sin tope no puede ser inferior a la facturación operativa.")

    parametros_centrales = parametros("central")
    coste_esperado = parametros_centrales["coste_anual_club"] * (
        0.6
        + 0.4
        * evaluacion["socios_captables"]
        / parametros_centrales["capacidad"]
    )
    if not np.allclose(
        evaluacion["coste_anual_escalado"],
        coste_esperado,
        rtol=1e-10,
        atol=1e-6,
    ):
        raise ValueError("El coste anual escalado no coincide con la fórmula definida.")
    margen_esperado = (
        evaluacion["facturacion_sin_tope_capacidad"] - coste_esperado
    )
    if not np.allclose(
        evaluacion["margen_escalado_eur"],
        margen_esperado,
        rtol=1e-10,
        atol=1e-6,
    ):
        raise ValueError("El margen escalado no coincide con la fórmula definida.")

    bajo_capacidad = evaluacion["ratio_capacidad"].le(1)
    if not np.allclose(
        evaluacion.loc[bajo_capacidad, "facturacion_sin_tope_capacidad"],
        evaluacion.loc[bajo_capacidad, "facturacion_anual"],
        rtol=1e-10,
        atol=1e-6,
    ):
        raise ValueError("Ambas facturaciones deben coincidir si no se alcanza la capacidad.")

    if len(selecciones["baseline"]) != 5:
        raise ValueError("El baseline debe seleccionar exactamente cinco municipios.")

    for clave in ("baseline", "modelo", "diversificada"):
        if len(selecciones[clave]) > 5:
            raise ValueError("Ninguna estrategia puede seleccionar más de cinco municipios.")

    for clave in ("modelo", "diversificada"):
        seleccion = selecciones[clave]
        if seleccion["municipality_code"].duplicated().any():
            raise ValueError(f"La selección '{clave}' contiene municipios duplicados.")
        if not (
            seleccion["candidate_flag"]
            & seleccion["viable"]
            & seleccion["quality_flag"]
        ).all():
            raise ValueError(
                f"La selección '{clave}' solo puede incluir candidatos viables con calidad."
            )

    recuento = selecciones["diversificada"]["cluster"].value_counts()
    if recuento.gt(2).any() or recuento.eq(2).sum() > 1:
        raise ValueError("El Modelo diversificado solo puede repetir un cluster una vez.")

    flag_esperado = (
        pd.to_numeric(evaluacion["expected_gyms"], errors="coerce").gt(0)
        & evaluacion["weighted_observed_vs_expected_pct"].ge(50)
    )
    if not evaluacion["quality_flag"].eq(flag_esperado).all():
        raise ValueError("quality_flag no coincide con el control ponderado >= 50 %.")

    if int(frecuencias["apariciones"].sum()) != len(detalle):
        raise ValueError("La suma de apariciones no coincide con las plazas seleccionadas.")

    if detalle["escenario"].astype(str).str.contains("todo_igual").any():
        raise ValueError("La sensibilidad no debe incluir el escenario todo_igual.")


def construir_archivos_salida(
    selecciones,
    ranking_modelo_completo,
    sustituciones_calidad,
    comparacion,
    evaluacion,
    detalle,
    frecuencias,
):
    """Diccionario nombre de archivo -> tabla. Lo usan main() y el notebook 04."""
    return {
        "baseline_central.csv": selecciones["baseline"],
        "seleccion_modelo_central.csv": selecciones["modelo"],
        "modelo_pendiente_validacion.csv": selecciones["pendientes_calidad"],
        "ranking_modelo_completo.csv": ranking_modelo_completo,
        "sustituciones_por_calidad.csv": sustituciones_calidad,
        "seleccion_diversificada_clusters_central.csv": selecciones["diversificada"],
        "comparacion_estrategias_central.csv": comparacion,
        "municipios_evaluados_central.csv": evaluacion,
        "sensibilidad_detalle.csv": detalle,
        "sensibilidad_frecuencias.csv": frecuencias,
    }


# ============================================================
# MAIN
# ============================================================

def main():
    datos = cargar()
    parametros_centrales = parametros("central")

    evaluacion = evaluar(
        datos,
        escenario="central",
        pesos="central",
        regla="C",
        con_candidatos=True,
    )

    (
        modelo,
        pendientes_calidad,
        ranking_modelo_completo,
        sustituciones_calidad,
    ) = seleccionar_modelo_con_calidad(evaluacion, n=5)

    selecciones = {
        "baseline": top5_baseline(evaluacion),
        "modelo": modelo,
        "diversificada": top5_diversificado_clusters(evaluacion),
        "pendientes_calidad": pendientes_calidad,
    }

    detalle, frecuencias = sensibilidad(datos)
    frecuencias = incorporar_calidad_central_en_robustez(frecuencias, evaluacion)

    validar_resultados_centrales(evaluacion, selecciones, detalle, frecuencias)

    comparacion = crear_comparacion_estrategias(selecciones)

    informe = crear_tablas_definitivas_md(
        selecciones=selecciones,
        comparacion=comparacion,
        evaluacion=evaluacion,
        frecuencias=frecuencias,
        sustituciones_calidad=sustituciones_calidad,
        parametros_centrales=parametros_centrales,
    )

    archivos = construir_archivos_salida(
        selecciones,
        ranking_modelo_completo,
        sustituciones_calidad,
        comparacion,
        evaluacion,
        detalle,
        frecuencias,
    )
    salidas = guardar_salidas_negocio(archivos, informe)
    obsoletos_s3 = limpiar_salidas_obsoletas_s3()
    if obsoletos_s3:
        print("Salidas obsoletas eliminadas de S3:", ", ".join(obsoletos_s3))

    mostrar("Comparación de estrategias", comparacion)
    print("Tablas definitivas:", salidas[NOMBRE_INFORME])
    print("Salidas de negocio:", ", ".join(map(str, salidas.values())))

    return {
        "selecciones": selecciones,
        "comparacion": comparacion,
        "evaluacion": evaluacion,
        "ranking_modelo_completo": ranking_modelo_completo,
        "sustituciones_calidad": sustituciones_calidad,
        "sensibilidad_detalle": detalle,
        "sensibilidad_frecuencias": frecuencias,
        "tablas_definitivas_path": salidas[NOMBRE_INFORME],
    }


if __name__ == "__main__":
    main()
