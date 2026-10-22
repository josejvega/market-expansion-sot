"""Preparation of input variables for the municipality clustering model."""

import pandas as pd
from sklearn.preprocessing import StandardScaler

PESO_OTRAS_INSTALACIONES = 0.1
HABITANTES_POR_100_000 = 100_000
VARIABLES_CLUSTERING = [
    "population_18_50",
    "mean_net_income_per_person",
    "population_growth_pct",
]


def tasa_ponderada_de_competidores(municipios: pd.DataFrame) -> pd.DataFrame:
    """Add weighted competitors per 100,000 total inhabitants to each municipality."""
    if (municipios["population_total"] <= 0).any():
        raise ValueError("population_total debe ser mayor que cero.")

    datos = municipios.copy()
    competidores_ponderados = (
        datos["gyms_count"]
        + PESO_OTRAS_INSTALACIONES * datos["other_sports_facilities_count"]
    )
    datos["tasa_ponderada_de_competidores"] = (
        competidores_ponderados
        / datos["population_total"]
        * HABITANTES_POR_100_000
    )
    return datos


def seleccionar_variables_modelo(municipios: pd.DataFrame) -> pd.DataFrame:
    """Select the demographic and income variables used to cluster municipalities."""
    return municipios.loc[:, VARIABLES_CLUSTERING].copy()


def escalar_variables_modelo(variables: pd.DataFrame) -> pd.DataFrame:
    """Standardize clustering variables while preserving their labels and index."""
    scaler = StandardScaler()
    valores_escalados = scaler.fit_transform(variables)
    return pd.DataFrame(
        valores_escalados,
        columns=variables.columns,
        index=variables.index,
    )
