"""Build the per-User-Agent candidate ranking table."""

from __future__ import annotations

import pandas as pd

from pipeline_common import normalize_count_columns


CANDIDATE_SUMMARY_COLUMNS = [
    "AdminComment",
    "RecordCount",
    "UniqueIPs",
    "UniqueSubnet24",
    "UniqueSubnet16",
    "FirstSeenUtc",
    "LastSeenUtc",
    "ActiveMinutes",
]


def analyze(rows: pd.DataFrame) -> pd.DataFrame:
    """Rank AdminComment/User-Agent values from highest to lowest priority."""
    if rows.empty:
        return pd.DataFrame(columns=CANDIDATE_SUMMARY_COLUMNS)

    summary = (
        rows.groupby("AdminComment", dropna=False, sort=False)
        .agg(
            RecordCount=("_RecordWeight", "sum"),
            UniqueIPs=("ValidIPAddress", "nunique"),
            UniqueSubnet24=("ValidSubnet24", "nunique"),
            UniqueSubnet16=("ValidSubnet16", "nunique"),
            FirstSeenUtc=("CreatedOnUtcDate", "min"),
            LastSeenUtc=("CreatedOnUtcDate", "max"),
        )
        .reset_index()
    )

    summary["ActiveMinutes"] = (
        (summary["LastSeenUtc"] - summary["FirstSeenUtc"]).dt.total_seconds() / 60.0
    ).round(2)
    summary.loc[
        summary["FirstSeenUtc"].isna() | summary["LastSeenUtc"].isna(),
        "ActiveMinutes",
    ] = pd.NA
    summary = normalize_count_columns(
        summary,
        ["RecordCount", "UniqueIPs", "UniqueSubnet24", "UniqueSubnet16"],
    )
    return summary[CANDIDATE_SUMMARY_COLUMNS].sort_values(
        by=["RecordCount", "UniqueIPs", "UniqueSubnet24", "ActiveMinutes"],
        ascending=[False, False, False, False],
    )
