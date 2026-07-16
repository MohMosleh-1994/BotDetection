"""Build global /24 subnet usage counts across all User-Agents."""

from __future__ import annotations

import pandas as pd

from pipeline_common import normalize_count_columns


GLOBAL_SUBNET24_COLUMNS = ["RangeSubnet24", "RecordCount", "DistinctAdminComments"]


def analyze(rows: pd.DataFrame) -> pd.DataFrame:
    """Group valid /24 subnet values across all AdminComment values."""
    if rows.empty:
        return pd.DataFrame(columns=GLOBAL_SUBNET24_COLUMNS)

    valid_rows = rows.loc[rows["ValidSubnet24"].notna()].copy()
    if valid_rows.empty:
        return pd.DataFrame(columns=GLOBAL_SUBNET24_COLUMNS)

    result = (
        valid_rows.groupby("ValidSubnet24", dropna=False, sort=False)
        .agg(
            RecordCount=("_RecordWeight", "sum"),
            DistinctAdminComments=("AdminComment", "nunique"),
        )
        .reset_index()
        .rename(columns={"ValidSubnet24": "RangeSubnet24"})
    )
    result = normalize_count_columns(result, ["RecordCount", "DistinctAdminComments"])
    return result[GLOBAL_SUBNET24_COLUMNS].sort_values(
        by=["RecordCount", "DistinctAdminComments"],
        ascending=[False, False],
    )
