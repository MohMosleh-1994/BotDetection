"""Run in-memory per-User-Agent IP concentration analysis."""

from __future__ import annotations

import pandas as pd

from pipeline_common import normalize_count_columns, safe_percent


MIN_VALID_IP_RECORDS = 50
MIN_VALID_IP_DATA_COVERAGE_PERCENT = 20.0

IP_MEANINGFUL_CONCENTRATION_PERCENT = 5.0

IP_CONCENTRATION_THRESHOLD_1 = 5.0
IP_CONCENTRATION_THRESHOLD_2 = 10.0
IP_CONCENTRATION_THRESHOLD_3 = 20.0
IP_CONCENTRATION_THRESHOLD_4 = 30.0
IP_CONCENTRATION_THRESHOLD_5 = 50.0

IP_CONCENTRATION_SCORE_1 = 0
IP_CONCENTRATION_SCORE_2 = 1
IP_CONCENTRATION_SCORE_3 = 2
IP_CONCENTRATION_SCORE_4 = 3
IP_CONCENTRATION_SCORE_5 = 4
IP_CONCENTRATION_SCORE_6 = 5

IP_VOLUME_THRESHOLD_1 = 10
IP_VOLUME_THRESHOLD_2 = 25
IP_VOLUME_THRESHOLD_3 = 50
IP_VOLUME_THRESHOLD_4 = 100
IP_VOLUME_THRESHOLD_5 = 200

IP_VOLUME_SCORE_1 = 0
IP_VOLUME_SCORE_2 = 1
IP_VOLUME_SCORE_3 = 2
IP_VOLUME_SCORE_4 = 3
IP_VOLUME_SCORE_5 = 4
IP_VOLUME_SCORE_6 = 5

IP_PRIORITY_HIGH_MIN_SCORE = 8
IP_PRIORITY_MEDIUM_MIN_SCORE = 5

IP_ANALYSIS_COLUMNS = [
    "AdminComment",
    "TotalRecords",
    "RecordsWithIP",
    "ValidIPDataCoveragePercent",
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
    if coverage_percent < IP_CONCENTRATION_THRESHOLD_1:
        return IP_CONCENTRATION_SCORE_1
    if coverage_percent < IP_CONCENTRATION_THRESHOLD_2:
        return IP_CONCENTRATION_SCORE_2
    if coverage_percent < IP_CONCENTRATION_THRESHOLD_3:
        return IP_CONCENTRATION_SCORE_3
    if coverage_percent < IP_CONCENTRATION_THRESHOLD_4:
        return IP_CONCENTRATION_SCORE_4
    if coverage_percent < IP_CONCENTRATION_THRESHOLD_5:
        return IP_CONCENTRATION_SCORE_5
    return IP_CONCENTRATION_SCORE_6


def ip_volume_score(top_ip_records: float) -> int:
    """Score top-IP volume from 0 to 5."""
    if top_ip_records < IP_VOLUME_THRESHOLD_1:
        return IP_VOLUME_SCORE_1
    if top_ip_records < IP_VOLUME_THRESHOLD_2:
        return IP_VOLUME_SCORE_2
    if top_ip_records < IP_VOLUME_THRESHOLD_3:
        return IP_VOLUME_SCORE_3
    if top_ip_records < IP_VOLUME_THRESHOLD_4:
        return IP_VOLUME_SCORE_4
    if top_ip_records < IP_VOLUME_THRESHOLD_5:
        return IP_VOLUME_SCORE_5
    return IP_VOLUME_SCORE_6


def ip_priority(score: int) -> str:
    """Convert IP score into a priority label."""
    if score >= IP_PRIORITY_HIGH_MIN_SCORE:
        return "HIGH"
    if score >= IP_PRIORITY_MEDIUM_MIN_SCORE:
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
    totals["ValidIPDataCoveragePercent"] = safe_percent(
        totals["RecordsWithIP"], totals["TotalRecords"]
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

    sufficient_ip_evidence = (
        (result["RecordsWithIP"] >= MIN_VALID_IP_RECORDS)
        & (
            result["ValidIPDataCoveragePercent"]
            >= MIN_VALID_IP_DATA_COVERAGE_PERCENT
        )
    )
    result.loc[sufficient_ip_evidence, "IPConcentrationScore"] = result.loc[
        sufficient_ip_evidence,
        "TopIPCoverageFromValidIPRecordsPercent",
    ].map(ip_concentration_score)
    result.loc[sufficient_ip_evidence, "IPVolumeScore"] = result.loc[
        sufficient_ip_evidence,
        "TopIPRecords",
    ].map(ip_volume_score)
    no_meaningful_concentration = (
        sufficient_ip_evidence
        & (
            (result["IPConcentrationScore"] == IP_CONCENTRATION_SCORE_1)
            | (
                result["TopIPCoverageFromValidIPRecordsPercent"]
                < IP_MEANINGFUL_CONCENTRATION_PERCENT
            )
        )
    )

    scoreable_sample = sufficient_ip_evidence & ~no_meaningful_concentration
    result.loc[scoreable_sample, "IPScore"] = (
        result.loc[scoreable_sample, "IPConcentrationScore"]
        + result.loc[scoreable_sample, "IPVolumeScore"]
    )
    result["IPPriority"] = result["IPScore"].map(ip_priority)

    result["IPScoreReason"] = "Insufficient IP evidence"
    result.loc[
        sufficient_ip_evidence,
        "IPScoreReason",
    ] = "Moderate IP concentration"
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
