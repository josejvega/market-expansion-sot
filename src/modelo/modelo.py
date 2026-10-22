"""KMeans model fitting and evaluation helpers."""

from __future__ import annotations

from numbers import Integral
from typing import Iterable

import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
import plotly.express as px
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from src.modelo.prepara_variables_modelo import tasa_ponderada_de_competidores


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


def graficar_clusters_interactivo(
    variables_escaladas: pd.DataFrame,
    municipios: pd.DataFrame,
    etiquetas_cluster: Iterable[int],
):
    """Plot all clusters using a nonlinear display scale and hover details."""
    if variables_escaladas.shape[1] != 3:
        raise ValueError("La visualización requiere exactamente tres variables.")
    if "municipality_name" not in municipios.columns:
        raise ValueError("municipios debe incluir la columna municipality_name.")

    etiquetas = pd.Series(etiquetas_cluster).reset_index(drop=True)
    if len(etiquetas) != len(variables_escaladas) or len(municipios) != len(
        variables_escaladas
    ):
        raise ValueError(
            "Variables, municipios y etiquetas deben tener el mismo número de filas."
        )
    if etiquetas.isna().any():
        raise ValueError("Las etiquetas de cluster no pueden contener valores nulos.")

    datos_grafico = variables_escaladas.reset_index(drop=True).copy()
    datos_grafico["cluster"] = etiquetas.astype(str)
    datos_grafico["municipality_name"] = (
        municipios["municipality_name"].reset_index(drop=True).fillna("Sin nombre")
    )
    if "province" in municipios.columns:
        datos_grafico["province"] = (
            municipios["province"].reset_index(drop=True).fillna("Sin provincia")
        )
    hover_data = {columna: False for columna in variables_escaladas.columns}
    labels = {}
    for columna in variables_escaladas.columns:
        columna_original = f"{columna}_valor_estandarizado"
        datos_grafico[columna_original] = datos_grafico[columna]
        datos_grafico[columna] = np.arcsinh(datos_grafico[columna])
        hover_data[columna_original] = ":.2f"
        labels[columna] = f"asinh({columna})"
        labels[columna_original] = f"{columna} (valor estandarizado)"
    if "province" in datos_grafico.columns:
        hover_data["province"] = True

    matriz_dispersion = px.scatter_matrix(
        datos_grafico,
        dimensions=variables_escaladas.columns.tolist(),
        color="cluster",
        hover_name="municipality_name",
        hover_data=hover_data,
        labels=labels,
        title="Clusters: variables estandarizadas con escala asinh para visualización",
    )
    matriz_dispersion.update_traces(diagonal_visible=True, showupperhalf=False)
    matriz_dispersion.update_layout(height=850)
    return matriz_dispersion


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
