"""Train K-means on local Gold and export municipality cluster assignments."""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from src.procesado.common.paths import DATA_DIR, GOLD_TABLE_PATH

LOGGER = logging.getLogger(__name__)
CLUSTERS_PATH = DATA_DIR / "resultados" / "clusters.csv"
EXPECTED_MUNICIPALITIES = 785
MIN_CLUSTER_SIZE = 30
RANDOM_STATE = 42
N_INIT = 20
MIN_K = 2
FEATURE_COLUMNS = [
    "population_18_50",
    "population_growth_pct",
    "mean_net_income_per_person",
]
TRANSFORMED_FEATURES = [
    "log1p_population_18_50",
    "population_growth_pct",
    "mean_net_income_per_person",
]


@dataclass
class ModelResult:
    clusters: pd.DataFrame
    evaluation: pd.DataFrame
    profiles: pd.DataFrame
    model: KMeans
    scaler: StandardScaler
    income_median: float
    imputed_municipalities: list[str]


def max_evaluable_k(
    n_municipalities: int,
    min_cluster_size: int | None = None,
) -> int:
    """Return the largest k compatible with the minimum cluster size."""
    if min_cluster_size is None:
        min_cluster_size = MIN_CLUSTER_SIZE
    if n_municipalities < 1:
        raise ValueError("The number of municipalities must be positive.")
    if min_cluster_size < 1:
        raise ValueError("The minimum cluster size must be positive.")
    return n_municipalities // min_cluster_size


def _validate_codes(table: pd.DataFrame) -> pd.Series:
    if "municipality_code" not in table.columns:
        raise ValueError("Missing municipality_code column.")
    codes = table["municipality_code"].astype("string")
    if len(codes) != EXPECTED_MUNICIPALITIES:
        raise ValueError(
            f"Expected {EXPECTED_MUNICIPALITIES} municipalities, got {len(codes)}."
        )
    if not codes.str.fullmatch(r"\d{5}").fillna(False).all():
        raise ValueError("Municipality codes must be five-digit strings.")
    if codes.duplicated().any():
        raise ValueError("Municipality codes must be unique.")
    return codes


def train_model(gold: pd.DataFrame) -> ModelResult:
    """Select the best eligible k by silhouette."""
    _validate_codes(gold)
    missing_columns = sorted(set(FEATURE_COLUMNS).difference(gold.columns))
    if missing_columns:
        raise ValueError(f"Missing model feature columns: {missing_columns}")

    ordered = gold.sort_values("municipality_code", kind="stable").reset_index(drop=True)
    max_k = max_evaluable_k(len(ordered))
    k_values = range(MIN_K, max_k + 1)
    if max_k < MIN_K:
        raise ValueError(
            f"No k in {MIN_K}..{max_k} satisfies the minimum of "
            f"{MIN_CLUSTER_SIZE} municipalities per cluster."
        )
    features = ordered.loc[:, FEATURE_COLUMNS].apply(
        pd.to_numeric, errors="raise"
    ).astype("float64")
    if features[FEATURE_COLUMNS[:2]].isna().any().any():
        raise ValueError("Population and population growth cannot contain missing values.")
    if np.isinf(features.to_numpy()).any():
        raise ValueError("Model features cannot contain infinite values.")
    if features["population_18_50"].le(0).any():
        raise ValueError("Population aged 18 to 50 must be positive.")
    if features["mean_net_income_per_person"].dropna().lt(0).any():
        raise ValueError("Income cannot be negative.")
    income_median = float(features["mean_net_income_per_person"].median())
    if not np.isfinite(income_median):
        raise ValueError("At least one observed income is required for median imputation.")
    missing_income = features["mean_net_income_per_person"].isna()
    imputed_municipalities = ordered.loc[
        missing_income, "municipality_code"
    ].tolist()
    if imputed_municipalities:
        LOGGER.warning(
            "Imputing income for %s municipalities with median %.2f: %s",
            len(imputed_municipalities),
            income_median,
            ", ".join(imputed_municipalities),
        )
    features["mean_net_income_per_person"] = (
        features["mean_net_income_per_person"].fillna(income_median)
    )
    transformed = features.copy()
    transformed["population_18_50"] = np.log1p(transformed["population_18_50"])
    transformed.columns = TRANSFORMED_FEATURES
    scaler = StandardScaler()
    scaled = scaler.fit_transform(transformed)
    if len(np.unique(scaled, axis=0)) < max_k:
        raise ValueError(
            f"At least {max_k} distinct feature vectors are required to evaluate "
            f"k={MIN_K}..{max_k}."
        )

    models: dict[int, KMeans] = {}
    rows = []
    for k in k_values:
        model = KMeans(n_clusters=k, random_state=RANDOM_STATE, n_init=N_INIT)
        labels = model.fit_predict(scaled)
        sizes = np.bincount(labels, minlength=k)
        rows.append(
            {
                "k": k,
                "inertia": float(model.inertia_),
                "silhouette": float(silhouette_score(scaled, labels)),
                "min_cluster_size": int(sizes.min()),
                "max_cluster_size": int(sizes.max()),
                "eligible": bool(sizes.min() >= MIN_CLUSTER_SIZE),
            }
        )
        models[k] = model

    evaluation = pd.DataFrame(rows)
    eligible = evaluation.loc[evaluation["eligible"]].sort_values(
        ["silhouette", "k"], ascending=[False, True], kind="stable"
    )
    if eligible.empty:
        raise ValueError(
            f"No k in {MIN_K}..{max_k} satisfies the minimum of "
            f"{MIN_CLUSTER_SIZE} municipalities per cluster.\n"
            + evaluation.to_string(index=False)
        )
    selected_k = int(eligible.iloc[0]["k"])
    model = models[selected_k]
    evaluation["selected"] = evaluation["k"].eq(selected_k)
    clusters = pd.DataFrame(
        {
            "municipality_code": ordered["municipality_code"].astype("string"),
            "cluster": model.labels_.astype("int64"),
        }
    )
    profiles = features.assign(cluster=model.labels_).groupby("cluster").agg(
        municipalities=("population_18_50", "size"),
        population_18_50_median=("population_18_50", "median"),
        population_growth_pct_median=("population_growth_pct", "median"),
        income_median=("mean_net_income_per_person", "median"),
    ).reset_index()
    LOGGER.info(
        "Selected k=%s; silhouette=%.4f; minimum cluster size=%s.",
        selected_k,
        eligible.iloc[0]["silhouette"],
        eligible.iloc[0]["min_cluster_size"],
    )
    return ModelResult(
        clusters, evaluation, profiles, model, scaler,
        income_median, imputed_municipalities,
    )


def save_clusters(clusters: pd.DataFrame, output_path: Path = CLUSTERS_PATH) -> Path:
    """Write exactly 785 unique codes and integer labels, preserving leading zeros."""
    if clusters.columns.tolist() != ["municipality_code", "cluster"]:
        raise ValueError("Output columns must be exactly municipality_code and cluster.")
    _validate_codes(clusters)
    labels = pd.to_numeric(clusters["cluster"], errors="raise")
    if (
        labels.isna().any()
        or not np.isfinite(labels.to_numpy(dtype=float)).all()
        or labels.lt(0).any()
        or labels.mod(1).ne(0).any()
    ):
        raise ValueError("Cluster labels must be non-negative integers.")
    output = clusters.assign(cluster=labels.astype("int64")).sort_values(
        "municipality_code", kind="stable"
    )
    output_path = Path(output_path)
    if output_path.suffix.lower() != ".csv":
        raise ValueError("Cluster output must use the .csv extension.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(".csv.tmp")
    try:
        output.to_csv(temporary_path, index=False, encoding="utf-8")
        temporary_path.replace(output_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    LOGGER.info("Saved %s municipality assignments to %s.", len(output), output_path)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, default=GOLD_TABLE_PATH)
    parser.add_argument("--output", type=Path, default=CLUSTERS_PATH)
    args = parser.parse_args()
    if args.gold.resolve() == args.output.resolve():
        parser.error("The output must not overwrite Gold.")
    logging.basicConfig(level=logging.INFO)
    result = train_model(pd.read_parquet(args.gold))
    print(result.evaluation.to_string(index=False))
    print(result.profiles.to_string(index=False))
    save_clusters(result.clusters, args.output)


if __name__ == "__main__":
    main()
