"""Build global IP usage counts across all User-Agents."""

from __future__ import annotations

import pandas as pd

from pipeline_common import normalize_count_columns


GLOBAL_IP_COLUMNS = ["IPAddress", "RecordCount", "DistinctAdminComments"]


def analyze(rows: pd.DataFrame) -> pd.DataFrame:
    """Group valid first IP addresses across all AdminComment values."""
    if rows.empty:
        return pd.DataFrame(columns=GLOBAL_IP_COLUMNS)

    valid_rows = rows.loc[rows["ValidIPAddress"].notna()].copy()
    if valid_rows.empty:
        return pd.DataFrame(columns=GLOBAL_IP_COLUMNS)

    result = (
        valid_rows.groupby("ValidIPAddress", dropna=False, sort=False)
        .agg(
            RecordCount=("_RecordWeight", "sum"),
            DistinctAdminComments=("AdminComment", "nunique"),
        )
        .reset_index()
        .rename(columns={"ValidIPAddress": "IPAddress"})
    )
    result = normalize_count_columns(result, ["RecordCount", "DistinctAdminComments"])
    return result[GLOBAL_IP_COLUMNS].sort_values(
        by=["RecordCount", "DistinctAdminComments"],
        ascending=[False, False],
    )
