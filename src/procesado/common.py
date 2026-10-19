"""Shared helpers for cleaning INE municipality data."""

from __future__ import annotations

import pandas as pd


def split_ine_municipality_codes(municipalities: pd.Series) -> pd.DataFrame:
    """Return municipality names and province codes from INE municipality values."""
    parts = municipalities.astype("string").str.extract(
        r"^\s*(\d{5})\s+(.+?)\s*$"
    )
    if parts.isna().to_numpy().any():
        raise ValueError("Municipios must contain a five-digit code followed by a name.")

    return pd.DataFrame(
        {
            "municipality": parts[1],
            "province_code": parts[0].str[:2],
        },
        index=municipalities.index,
    )
