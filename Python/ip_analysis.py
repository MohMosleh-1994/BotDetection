"""Run in-memory per-User-Agent IP concentration analysis."""

from __future__ import annotations

import pandas as pd

from pipeline_common import normalize_count_columns, safe_percent


IP_ANALYSIS_COLUMNS = [
    "AdminComment",
    "TotalRecords",
    "RecordsWithIP",
    "UniqueIPs",
    "TopIPAddress",
    "TopIPRecords",
    "TopIPCoverageFromTotalRecordsPercent",
    "TopIPCoverageFromValidIPRecordsPercent",
    "IPConcentrationScore",
    "IPVolumeScore",
    "IPScore",
    "IPPriority",
    "IPScoreReason",
]


def ip_concentration_score(coverage_percent: float) -> int:
    """Score top-IP concentration from 0 to 5."""
    if coverage_percent < 5:
        return 0
    if coverage_percent < 10:
        return 1
    if coverage_percent < 20:
        return 2
    if coverage_percent < 30:
        return 3
    if coverage_percent < 50:
        return 4
    return 5


def ip_volume_score(top_ip_records: float) -> int:
    """Score top-IP volume from 0 to 5."""
    if top_ip_records < 10:
        return 0
    if top_ip_records < 25:
        return 1
    if top_ip_records < 50:
        return 2
    if top_ip_records < 100:
        return 3
    if top_ip_records < 200:
        return 4
    return 5


def ip_priority(score: int) -> str:
    """Convert IP score into a priority label."""
    if score >= 8:
        return "HIGH"
    if score >= 5:
        return "MEDIUM"
    return "LOW"


def analyze(rows: pd.DataFrame) -> pd.DataFrame:
    """Calculate IP concentration metrics for every AdminComment."""
    if rows.empty:
        return pd.DataFrame(columns=IP_ANALYSIS_COLUMNS)

    working = rows[["AdminComment", "_RecordWeight", "ValidIPAddress"]].copy()
    working["IPWeight"] = working["_RecordWeight"].where(working["ValidIPAddress"].notna(), 0)

    totals = (
        working.groupby("AdminComment", dropna=False, sort=False)
        .agg(
            TotalRecords=("_RecordWeight", "sum"),
            RecordsWithIP=("IPWeight", "sum"),
            UniqueIPs=("ValidIPAddress", "nunique"),
        )
        .reset_index()
    )

    valid_ips = working.loc[working["ValidIPAddress"].notna()]
    if not valid_ips.empty:
        ip_counts = (
            valid_ips.groupby(["AdminComment", "ValidIPAddress"], dropna=False, sort=False)[
                "_RecordWeight"
            ]
            .sum()
            .reset_index(name="TopIPRecords")
        )
        top_ip = (
            ip_counts.sort_values(
                by=["AdminComment", "TopIPRecords", "ValidIPAddress"],
                ascending=[True, False, True],
            )
            .drop_duplicates(subset=["AdminComment"], keep="first")
            .rename(columns={"ValidIPAddress": "TopIPAddress"})
        )
    else:
        top_ip = pd.DataFrame(columns=["AdminComment", "TopIPAddress", "TopIPRecords"])

    result = totals.merge(top_ip, on="AdminComment", how="left")
    result["TopIPRecords"] = pd.to_numeric(result["TopIPRecords"], errors="coerce").fillna(0)
    result["TopIPCoverageFromTotalRecordsPercent"] = safe_percent(
        result["TopIPRecords"], result["TotalRecords"]
    )
    result["TopIPCoverageFromValidIPRecordsPercent"] = safe_percent(
        result["TopIPRecords"], result["RecordsWithIP"]
    )
    result["IPConcentrationScore"] = 0
    result["IPVolumeScore"] = 0
    result["IPScore"] = 0

    eligible_sample = result["TotalRecords"] >= 100
    result.loc[eligible_sample, "IPConcentrationScore"] = result.loc[
        eligible_sample,
        "TopIPCoverageFromValidIPRecordsPercent",
    ].map(ip_concentration_score)
    result.loc[eligible_sample, "IPVolumeScore"] = result.loc[
        eligible_sample,
        "TopIPRecords",
    ].map(ip_volume_score)
    no_meaningful_concentration = (
        eligible_sample
        & (
            (result["IPConcentrationScore"] == 0)
            | (result["TopIPCoverageFromValidIPRecordsPercent"] < 5)
        )
    )

    scoreable_sample = eligible_sample & ~no_meaningful_concentration
    result.loc[scoreable_sample, "IPScore"] = (
        result.loc[scoreable_sample, "IPConcentrationScore"]
        + result.loc[scoreable_sample, "IPVolumeScore"]
    )
    result["IPPriority"] = result["IPScore"].map(ip_priority)

    result["IPScoreReason"] = "Moderate IP concentration"
    result.loc[
        result["IPConcentrationScore"] >= 4,
        "IPScoreReason",
    ] = "High IP concentration"
    result.loc[
        (result["IPConcentrationScore"] >= 4) & (result["IPVolumeScore"] >= 4),
        "IPScoreReason",
    ] = "High IP concentration + high IP volume"
    result.loc[
        no_meaningful_concentration,
        "IPScoreReason",
    ] = "No meaningful IP concentration"
    result.loc[
        ~eligible_sample,
        "IPScoreReason",
    ] = "Insufficient sample size"

    result = normalize_count_columns(
        result,
        [
            "TotalRecords",
            "RecordsWithIP",
            "UniqueIPs",
            "TopIPRecords",
            "IPConcentrationScore",
            "IPVolumeScore",
            "IPScore",
        ],
    )
    return result[IP_ANALYSIS_COLUMNS].sort_values(
        by=[
            "IPScore",
            "TopIPCoverageFromValidIPRecordsPercent",
            "TopIPRecords",
            "TotalRecords",
        ],
        ascending=[False, False, False, False],
    )
