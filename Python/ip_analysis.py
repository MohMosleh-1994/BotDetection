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
    "IPEvidenceDecision",
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


def ip_score_reason(row: pd.Series) -> str:
    """Explain what drove the IP score."""
    if row["TotalRecords"] < 100:
        return "Insufficient sample size"
    if row["IPConcentrationScore"] >= 4 and row["IPVolumeScore"] >= 4:
        return "High concentration + High volume"
    if row["IPConcentrationScore"] >= 4:
        return "High concentration"
    if row["IPVolumeScore"] >= 4:
        return "High volume"
    if row["IPConcentrationScore"] > row["IPVolumeScore"]:
        return "Concentration-driven score"
    if row["IPVolumeScore"] > row["IPConcentrationScore"]:
        return "Volume-driven score"
    return "Low concentration and volume"


def ip_evidence_decision(row: pd.Series) -> str:
    """Keep the earlier evidence label for review compatibility."""
    if row["TotalRecords"] < 100 and row["UniqueIPs"] < 100:
        return "LOW EVIDENCE"
    if row["TopIPCoverageFromValidIPRecordsPercent"] >= 20:
        return "WORTH CHECKING"
    return "LOW IP CONCENTRATION"


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
    result["IPConcentrationScore"] = result[
        "TopIPCoverageFromValidIPRecordsPercent"
    ].map(ip_concentration_score)
    result["IPVolumeScore"] = result["TopIPRecords"].map(ip_volume_score)
    result.loc[result["TotalRecords"] < 100, ["IPConcentrationScore", "IPVolumeScore"]] = 0
    result["IPScore"] = result["IPConcentrationScore"] + result["IPVolumeScore"]
    result["IPPriority"] = result["IPScore"].map(ip_priority)
    result["IPScoreReason"] = result.apply(ip_score_reason, axis=1)
    result["IPEvidenceDecision"] = result.apply(ip_evidence_decision, axis=1)

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
