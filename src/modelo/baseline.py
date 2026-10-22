def top5_baseline(df_eval):
    """Práctica actual del cliente: los 5 con más población 18-50."""
    return df_eval.sort_values(
        ["population_18_50", "municipality_code"],
        ascending=[False, True],
        kind="stable",
    ).head(5)