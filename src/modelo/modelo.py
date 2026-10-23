"""KMeans model fitting and evaluation helpers."""

from __future__ import annotations

from numbers import Integral
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterable

import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
import plotly.express as px
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from src.common.storage import get_storage_settings
from src.common.upload_to_s3 import upload_files_to_s3
from src.modelo.prepara_variables_modelo import tasa_ponderada_de_competidores
from src.procesado.common.paths import DATA_DIR

RESULTS_DIR = DATA_DIR / "results"
RESULTS_PREFIX = "results"
MUNICIPALITY_CANDIDATES_FILENAME = "municipios_candidatos.parquet"
MUNICIPALITY_CLUSTERS_FILENAME = "municipios_clusters.parquet"


def obtener_inercias(k_values: Iterable[int], X_escalado: np.ndarray) -> list[float]:
    """Return KMeans inertias for candidate k values using scaled features."""
    valores_k = _validar_k_values(
        k_values,
        X_escalado,
        permitir_un_cluster=True,
    )
    inercias = []
    for n_clusters in valores_k:
        kmeans = KMeans(n_clusters=n_clusters, random_state=0, n_init=10).fit(
            X_escalado
        )
        inercias.append(float(kmeans.inertia_))
    return inercias


def obtener_silhouette_scores(
    k_values: Iterable[int],
    X_escalado: np.ndarray,
) -> list[float]:
    """Return silhouette scores for candidate k values using scaled features."""
    valores_k = _validar_k_values(
        k_values,
        X_escalado,
        permitir_un_cluster=False,
    )
    silhouette_scores = []
    for n_clusters in valores_k:
        kmeans = KMeans(n_clusters=n_clusters, random_state=0, n_init=10).fit(
            X_escalado
        )
        n_labels = np.unique(kmeans.labels_).size
        if not 2 <= n_labels < X_escalado.shape[0]:
            raise ValueError(
                f"No se puede calcular silhouette para k={n_clusters}: "
                "el clustering debe producir entre 2 y n-1 grupos."
            )
        score = silhouette_score(X_escalado, kmeans.labels_)
        silhouette_scores.append(float(score))
    return silhouette_scores


def crear_modelo_kmeans(n_clusters: int, X_escalado: np.ndarray) -> KMeans:
    """Fit KMeans with a chosen cluster count on scaled features."""
    if X_escalado.ndim != 2:
        raise ValueError("X_escalado debe ser una matriz bidimensional.")
    if not isinstance(n_clusters, Integral) or isinstance(n_clusters, bool):
        raise ValueError("n_clusters debe ser un entero.")
    if not 1 <= n_clusters <= X_escalado.shape[0]:
        raise ValueError(
            f"n_clusters debe estar entre 1 y {X_escalado.shape[0]}."
        )
    return KMeans(
        n_clusters=int(n_clusters),
        random_state=0,
        n_init=10,
    ).fit(X_escalado)


def graficar_metricas_kmeans(
    k_inercia: Iterable[int],
    k_silhouette: Iterable[int],
    X_escalado: np.ndarray,
):
    """Calculate and plot inertia and silhouette scores for separate k ranges."""
    valores_inercia = list(k_inercia)
    valores_silhouette = list(k_silhouette)
    inercias = obtener_inercias(valores_inercia, X_escalado)
    silhouette_scores = obtener_silhouette_scores(valores_silhouette, X_escalado)

    figura, ejes = plt.subplots(1, 2, figsize=(12, 4))
    ejes[0].plot(valores_inercia, inercias, marker="o")
    ejes[0].set_title("Método del codo")
    ejes[0].set_xlabel("Número de clusters (k)")
    ejes[0].set_ylabel("Inercia")
    ejes[0].set_xticks(valores_inercia)
    ejes[0].grid(True, alpha=0.3)

    ejes[1].plot(valores_silhouette, silhouette_scores, marker="o")
    ejes[1].set_title("Coeficiente silhouette")
    ejes[1].set_xlabel("Número de clusters (k)")
    ejes[1].set_ylabel("Silhouette score")
    ejes[1].set_xticks(valores_silhouette)
    ejes[1].grid(True, alpha=0.3)

    figura.tight_layout()
    plt.show()
    return figura, ejes


def graficar_metricas_y_obtener_mejor_k(
    X_escalado: np.ndarray,
    k_maximo: int = 10,
) -> int:
    """Plot KMeans metrics, show their table, and return the best k by silhouette."""
    if X_escalado.ndim != 2 or X_escalado.shape[0] < 3:
        raise ValueError("Se necesitan al menos tres observaciones en una matriz 2D.")
    if not isinstance(k_maximo, Integral) or isinstance(k_maximo, bool) or k_maximo < 2:
        raise ValueError("k_maximo debe ser un entero mayor o igual que 2.")

    k_maximo = min(int(k_maximo), X_escalado.shape[0] - 1)
    valores_inercia = list(range(1, k_maximo + 1))
    valores_silhouette = list(range(2, k_maximo + 1))
    inercias = obtener_inercias(valores_inercia, X_escalado)
    silhouette_scores = obtener_silhouette_scores(valores_silhouette, X_escalado)

    tabla_metricas = pd.DataFrame(
        {
            "inercia": inercias,
            "silhouette": [np.nan, *silhouette_scores],
        },
        index=pd.Index(valores_inercia, name="k"),
    )
    figura, ejes = plt.subplots(1, 2, figsize=(12, 4))
    ejes[0].plot(valores_inercia, inercias, marker="o")
    ejes[0].set_title("Método del codo")
    ejes[0].set_xlabel("Número de clusters (k)")
    ejes[0].set_ylabel("Inercia")
    ejes[0].set_xticks(valores_inercia)
    ejes[0].grid(True, alpha=0.3)
    ejes[1].plot(valores_silhouette, silhouette_scores, marker="o")
    ejes[1].set_title("Coeficiente silhouette")
    ejes[1].set_xlabel("Número de clusters (k)")
    ejes[1].set_ylabel("Silhouette score")
    ejes[1].set_xticks(valores_silhouette)
    ejes[1].grid(True, alpha=0.3)
    figura.tight_layout()
    plt.show()

    mejor_k = int(tabla_metricas["silhouette"].idxmax())
    print(tabla_metricas.round(3).to_string())
    print(
        f"\nk recomendado por silhouette: {mejor_k} "
        "(la inercia se usa para valorar visualmente el codo)."
    )
    return mejor_k


def seleccionar_municipios_bajo_media_cluster(
    municipios: pd.DataFrame,
    etiquetas_cluster: pd.Series | np.ndarray | list[int],
) -> pd.DataFrame:
    """Return municipalities below their cluster's mean weighted competitor rate."""
    etiquetas = pd.Series(etiquetas_cluster).reset_index(drop=True)
    if len(etiquetas) != len(municipios):
        raise ValueError(
            "Debe haber exactamente una etiqueta de cluster por municipio."
        )
    if etiquetas.isna().any():
        raise ValueError("Las etiquetas de cluster no pueden contener valores nulos.")

    datos = tasa_ponderada_de_competidores(municipios)
    datos["cluster"] = etiquetas.to_numpy()
    datos["media_tasa_ponderada_cluster"] = datos.groupby("cluster")[
        "tasa_ponderada_de_competidores"
    ].transform("mean")
    return datos.loc[
        datos["tasa_ponderada_de_competidores"]
        < datos["media_tasa_ponderada_cluster"]
    ].copy()


def seleccionar_y_guardar_municipios_candidatos(
    municipios: pd.DataFrame,
    etiquetas_cluster: pd.Series | np.ndarray | list[int],
) -> pd.DataFrame:
    """Select candidates and persist candidate and complete cluster outputs."""
    candidatos = seleccionar_municipios_bajo_media_cluster(
        municipios,
        etiquetas_cluster,
    )
    settings = get_storage_settings()
    should_persist = settings.save_locally or settings.save_s3
    if should_persist and "municipality_code" not in municipios.columns:
        raise ValueError(
            "municipality_code es necesario para guardar las asignaciones de cluster."
        )
    etiquetas = pd.Series(etiquetas_cluster).reset_index(drop=True)
    asignaciones = pd.DataFrame()
    if should_persist:
        asignaciones = municipios.loc[:, ["municipality_code"]].reset_index(drop=True)
        asignaciones["cluster"] = etiquetas.to_numpy()

    def persist(output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        candidates_path = output_dir / MUNICIPALITY_CANDIDATES_FILENAME
        clusters_path = output_dir / MUNICIPALITY_CLUSTERS_FILENAME
        candidatos.to_parquet(candidates_path, index=False, compression="snappy")
        asignaciones.to_parquet(clusters_path, index=False, compression="snappy")
        if settings.save_s3:
            upload_files_to_s3(
                [candidates_path, clusters_path],
                prefix=RESULTS_PREFIX,
                bucket_name=settings.bucket_name,
                region_name=settings.region_name,
            )

    if settings.save_locally:
        persist(RESULTS_DIR)
    elif settings.save_s3:
        with TemporaryDirectory(prefix="market-expansion-results-") as directory:
            persist(Path(directory))

    return candidatos


def graficar_clusters_interactivo(
    variables_escaladas: pd.DataFrame,
    municipios: pd.DataFrame,
    etiquetas_cluster: Iterable[int],
):
    """Plot cluster pairs using original values and a logarithmic population axis."""
    if variables_escaladas.shape[1] != 3:
        raise ValueError("La visualización requiere exactamente tres variables.")
    columnas_grafico = [
        "municipality_name",
        "population_18_50",
        "population_growth_pct",
        "mean_net_income_per_person",
    ]
    faltantes = sorted(set(columnas_grafico).difference(municipios.columns))
    if faltantes:
        raise ValueError(f"Faltan columnas para graficar los clusters: {faltantes}")

    etiquetas = pd.Series(etiquetas_cluster).reset_index(drop=True)
    if len(etiquetas) != len(variables_escaladas) or len(municipios) != len(
        variables_escaladas
    ):
        raise ValueError(
            "Variables, municipios y etiquetas deben tener el mismo número de filas."
        )
    if etiquetas.isna().any():
        raise ValueError("Las etiquetas de cluster no pueden contener valores nulos.")
    datos_grafico = municipios.loc[:, columnas_grafico].reset_index(drop=True).copy()
    for columna in columnas_grafico[1:]:
        datos_grafico[columna] = pd.to_numeric(datos_grafico[columna], errors="raise")
    if datos_grafico["population_18_50"].le(0).any():
        raise ValueError(
            "population_18_50 debe ser mayor que cero para usar una escala logarítmica."
        )
    datos_grafico["cluster"] = etiquetas.astype(str)
    datos_grafico["municipality_name"] = datos_grafico[
        "municipality_name"
    ].fillna("Sin nombre")
    if "province" in municipios.columns:
        datos_grafico["province"] = municipios["province"].reset_index(
            drop=True
        ).fillna("Sin provincia")

    from plotly.graph_objects import Box, Scatter
    from plotly.subplots import make_subplots

    pares = [
        ("population_18_50", "population_growth_pct"),
        ("population_18_50", "mean_net_income_per_person"),
        ("mean_net_income_per_person", "population_growth_pct"),
    ]
    variables_boxplot = [
        "population_18_50",
        "mean_net_income_per_person",
        "population_growth_pct",
    ]
    etiquetas_ejes = {
        "population_18_50": "Población de 18 a 50 años",
        "population_growth_pct": "Crecimiento de población (%)",
        "mean_net_income_per_person": "Renta neta media por persona",
    }
    figura = make_subplots(
        rows=2,
        cols=3,
        specs=[[{"type": "xy"}] * 3, [{"type": "xy"}] * 3],
        subplot_titles=[
            "Población y crecimiento",
            "Población y renta",
            "Renta y crecimiento",
            "Distribución de población por cluster",
            "Distribución de renta por cluster",
            "Distribución de crecimiento por cluster",
        ],
    )
    orden_clusters = sorted(datos_grafico["cluster"].unique())
    colores = px.colors.qualitative.Plotly
    colores_cluster = {
        cluster: colores[indice % len(colores)]
        for indice, cluster in enumerate(orden_clusters)
    }
    for indice, (eje_x, eje_y) in enumerate(pares, start=1):
        for cluster in orden_clusters:
            grupo = datos_grafico.loc[datos_grafico["cluster"].eq(cluster)]
            figura.add_trace(
                Scatter(
                    x=grupo[eje_x],
                    y=grupo[eje_y],
                    mode="markers",
                    name=f"Cluster {cluster}",
                    legendgroup=cluster,
                    showlegend=indice == 1,
                    marker={"color": colores_cluster[cluster]},
                    text=grupo["municipality_name"],
                    hovertemplate=(
                        "%{text}<br>"
                        f"{etiquetas_ejes[eje_x]}: %{{x:,.2f}}<br>"
                        f"{etiquetas_ejes[eje_y]}: %{{y:,.2f}}"
                        "<extra></extra>"
                    ),
                ),
                row=1,
                col=indice,
            )
        figura.update_xaxes(
            title_text=etiquetas_ejes[eje_x],
            type="log" if eje_x == "population_18_50" else "linear",
            row=1,
            col=indice,
        )
        figura.update_yaxes(title_text=etiquetas_ejes[eje_y], row=1, col=indice)
    for indice, variable in enumerate(variables_boxplot, start=1):
        for cluster in orden_clusters:
            valores = datos_grafico.loc[
                datos_grafico["cluster"].eq(cluster), variable
            ]
            figura.add_trace(
                Box(
                    x=[cluster] * len(valores),
                    y=valores,
                    name=f"Cluster {cluster}",
                    marker_color=colores_cluster[cluster],
                    legendgroup=cluster,
                    showlegend=False,
                    boxpoints="outliers",
                    hovertemplate=(
                        f"Cluster {cluster}<br>{etiquetas_ejes[variable]}: "
                        "%{y:,.2f}<extra></extra>"
                    ),
                ),
                row=2,
                col=indice,
            )
        figura.update_xaxes(
            title_text="Cluster",
            categoryorder="array",
            categoryarray=orden_clusters,
            row=2,
            col=indice,
        )
        figura.update_yaxes(
            title_text=etiquetas_ejes[variable],
            type="log" if variable == "population_18_50" else "linear",
            row=2,
            col=indice,
        )
    figura.update_layout(
        title="Clusters municipales: relaciones y distribuciones en valores originales",
        height=900,
        legend_title_text="Cluster",
    )
    return figura


def _validar_k_values(
    k_values: Iterable[int],
    X_escalado: np.ndarray,
    *,
    permitir_un_cluster: bool,
) -> list[int]:
    if X_escalado.ndim != 2:
        raise ValueError("X_escalado debe ser una matriz bidimensional.")
    valores_k = list(k_values)
    minimo = 1 if permitir_un_cluster else 2
    maximo = X_escalado.shape[0] if permitir_un_cluster else X_escalado.shape[0] - 1
    if not valores_k:
        raise ValueError("k_values no puede estar vacío.")
    if any(not isinstance(k, Integral) or isinstance(k, bool) for k in valores_k):
        raise ValueError("Todos los valores de k deben ser enteros.")
    if any(k < minimo or k > maximo for k in valores_k):
        if permitir_un_cluster:
            raise ValueError(
                f"Para inercias, k debe estar entre 1 y {X_escalado.shape[0]}."
            )
        raise ValueError(
            "Para silhouette, k debe estar entre 2 y "
            f"{X_escalado.shape[0] - 1}."
        )
    return [int(k) for k in valores_k]
