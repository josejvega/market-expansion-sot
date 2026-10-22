"""Run reproducible K-means and business validation experiments."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score

from src.procesado.common.paths import DATA_DIR, GOLD_TABLE_PATH
from src.modelo.modelo import (
    FEATURE_COLUMNS,
    MIN_CLUSTER_SIZE,
    MIN_K,
    N_INIT,
    RANDOM_STATE,
    TRANSFORMED_FEATURES,
    max_evaluable_k,
    train_model,
)

DEFAULT_OUTPUT_DIR = DATA_DIR / "resultados" / "experimento_k"
STABILITY_SEEDS = (0, 1, 2, 3, 4, RANDOM_STATE)


def _scaled_features(gold: pd.DataFrame, reference) -> tuple[pd.DataFrame, pd.DataFrame, np.ndarray]:
    """Recreate the validated model matrix using the reference scaler."""
    ordered = gold.sort_values("municipality_code", kind="stable").reset_index(drop=True)
    features = ordered.loc[:, FEATURE_COLUMNS].apply(pd.to_numeric, errors="raise").astype("float64")
    features["mean_net_income_per_person"] = features["mean_net_income_per_person"].fillna(
        reference.income_median
    )
    transformed = features.copy()
    transformed["population_18_50"] = np.log1p(transformed["population_18_50"])
    transformed.columns = TRANSFORMED_FEATURES
    return ordered, features, reference.scaler.transform(transformed)


def _fit_k(scaled: np.ndarray, k: int, seed: int) -> tuple[KMeans, np.ndarray, int, int]:
    model = KMeans(n_clusters=k, random_state=seed, n_init=N_INIT)
    labels = model.fit_predict(scaled)
    sizes = np.bincount(labels, minlength=k)
    return model, labels, int(sizes.min()), int(sizes.max())


def run_experiment(
    gold_path: Path = GOLD_TABLE_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, pd.DataFrame]:
    """Run technical K-means evaluation, stability and cluster profiles."""
    gold = pd.read_parquet(gold_path)
    reference = train_model(gold)
    ordered, features, scaled = _scaled_features(gold, reference)
    max_k = max_evaluable_k(len(ordered))
    k_values = list(range(MIN_K, max_k + 1))

    evaluation_rows = []
    stability_rows = []
    for k in k_values:
        model, labels, min_size, max_size = _fit_k(scaled, k, RANDOM_STATE)
        eligible = min_size >= MIN_CLUSTER_SIZE
        evaluation_rows.append({
            "k": k,
            "inertia": float(model.inertia_),
            "silhouette": float(silhouette_score(scaled, labels)),
            "min_cluster_size": min_size,
            "max_cluster_size": max_size,
            "eligible": eligible,
            "selected_by_silhouette": bool(reference.evaluation.loc[
                reference.evaluation["k"].eq(k), "selected"
            ].iloc[0]),
        })
        if eligible:
            reference_labels = labels
            for seed in STABILITY_SEEDS:
                _, seed_labels, seed_min, seed_max = _fit_k(scaled, k, seed)
                stability_rows.append({
                    "k": k,
                    "seed": seed,
                    "min_cluster_size": seed_min,
                    "max_cluster_size": seed_max,
                    "eligible": seed_min >= MIN_CLUSTER_SIZE,
                    "ari_vs_random_state": float(
                        adjusted_rand_score(reference_labels, seed_labels)
                    ),
                    "silhouette": float(silhouette_score(scaled, seed_labels)),
                })

    evaluation = pd.DataFrame(evaluation_rows)
    stability = pd.DataFrame(stability_rows)
    selected_k = int(evaluation.loc[evaluation["selected_by_silhouette"], "k"].iloc[0])
    selected_labels = _fit_k(scaled, selected_k, RANDOM_STATE)[1]
    profiled = ordered.loc[:, ["municipality_code"]].copy()
    profiled = pd.concat([profiled, features], axis=1)
    profiled["cluster"] = selected_labels
    profiles = profiled.groupby("cluster").agg(
        municipalities=("municipality_code", "size"),
        population_18_50_median=("population_18_50", "median"),
        population_growth_pct_median=("population_growth_pct", "median"),
        income_median=("mean_net_income_per_person", "median"),
    ).reset_index()
    profiles.insert(0, "selected_k", selected_k)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    evaluation.to_csv(output_dir / "evaluacion_k.csv", index=False)
    stability.to_csv(output_dir / "estabilidad_k.csv", index=False)
    profiles.to_csv(output_dir / "perfiles_seleccion.csv", index=False)

    print(evaluation.to_string(index=False))
    print("\nPerfiles:")
    print(profiles.to_string(index=False))
    print(f"\nResultados guardados en: {output_dir}")
    return {
        "evaluation": evaluation,
        "stability": stability,
        "profiles": profiles,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, default=GOLD_TABLE_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    run_experiment(args.gold, args.output_dir)


if __name__ == "__main__":
    main()
