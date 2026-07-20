"""Run in-memory per-User-Agent /24 subnet concentration analysis."""

from __future__ import annotations

import pandas as pd

from pipeline_common import normalize_count_columns, safe_percent


MIN_VALID_SUBNET24_RECORDS = 200
MIN_VALID_SUBNET24_DATA_COVERAGE_PERCENT = 20.0

SUBNET24_CONCENTRATION_THRESHOLD_1 = 20.0
SUBNET24_CONCENTRATION_THRESHOLD_2 = 30.0
SUBNET24_CONCENTRATION_THRESHOLD_3 = 40.0
SUBNET24_CONCENTRATION_THRESHOLD_4 = 55.0
SUBNET24_CONCENTRATION_THRESHOLD_5 = 70.0

SUBNET24_SCORE_1 = 0
SUBNET24_SCORE_2 = 2
SUBNET24_SCORE_3 = 4
SUBNET24_SCORE_4 = 6
SUBNET24_SCORE_5 = 8
SUBNET24_SCORE_6 = 10

SUBNET24_PRIORITY_HIGH_MIN_SCORE = SUBNET24_SCORE_5
SUBNET24_PRIORITY_MEDIUM_MIN_SCORE = SUBNET24_SCORE_3

SUBNET24_ANALYSIS_COLUMNS = [
    "AdminComment",
    "TotalRecords",
    "RecordsWithSubnet24",
    "Subnet24DataCompletenessPercent",
    "UniqueSubnet24",
    "TopSubnet24",
    "TopSubnet24Records",
    "TopSubnet24CoverageFromTotalRecordsPercent",
    "TopSubnet24CoverageFromValidSubnet24RecordsPercent",
    "Subnet24Score",
    "Subnet24Priority",
    "Subnet24EvidenceDecision",
    "Subnet24ScoreReason",
]


def subnet24_score(concentration_percent: float) -> int:
    """Score top-/24 concentration from 0 to 10."""
    if concentration_percent < SUBNET24_CONCENTRATION_THRESHOLD_1:
        return SUBNET24_SCORE_1
    if concentration_percent < SUBNET24_CONCENTRATION_THRESHOLD_2:
        return SUBNET24_SCORE_2
    if concentration_percent < SUBNET24_CONCENTRATION_THRESHOLD_3:
        return SUBNET24_SCORE_3
    if concentration_percent < SUBNET24_CONCENTRATION_THRESHOLD_4:
        return SUBNET24_SCORE_4
    if concentration_percent < SUBNET24_CONCENTRATION_THRESHOLD_5:
        return SUBNET24_SCORE_5
    return SUBNET24_SCORE_6


def subnet24_priority(score: int) -> str:
    """Convert /24 score into a priority label."""
    if score >= SUBNET24_PRIORITY_HIGH_MIN_SCORE:
        return "HIGH"
    if score >= SUBNET24_PRIORITY_MEDIUM_MIN_SCORE:
        return "MEDIUM"
    return "LOW"


def analyze(rows: pd.DataFrame) -> pd.DataFrame:
    """Calculate /24 concentration metrics for every AdminComment."""
    if rows.empty:
        return pd.DataFrame(columns=SUBNET24_ANALYSIS_COLUMNS)

    working = rows[["AdminComment", "_RecordWeight", "ValidSubnet24"]].copy()
    working["Subnet24Weight"] = working["_RecordWeight"].where(
        working["ValidSubnet24"].notna(), 0
    )

    totals = (
        working.groupby("AdminComment", dropna=False, sort=False)
        .agg(
            TotalRecords=("_RecordWeight", "sum"),
            RecordsWithSubnet24=("Subnet24Weight", "sum"),
            UniqueSubnet24=("ValidSubnet24", "nunique"),
        )
        .reset_index()
    )
    totals["Subnet24DataCompletenessPercent"] = safe_percent(
        totals["RecordsWithSubnet24"], totals["TotalRecords"]
    )

    valid_subnets = working.loc[working["ValidSubnet24"].notna()]
    if not valid_subnets.empty:
        subnet_counts = (
            valid_subnets.groupby(["AdminComment", "ValidSubnet24"], dropna=False, sort=False)[
                "_RecordWeight"
            ]
            .sum()
            .reset_index(name="TopSubnet24Records")
        )
        top_subnet = (
            subnet_counts.sort_values(
                by=["AdminComment", "TopSubnet24Records", "ValidSubnet24"],
                ascending=[True, False, True],
            )
            .drop_duplicates(subset=["AdminComment"], keep="first")
            .rename(columns={"ValidSubnet24": "TopSubnet24"})
        )
    else:
        top_subnet = pd.DataFrame(columns=["AdminComment", "TopSubnet24", "TopSubnet24Records"])

    result = totals.merge(top_subnet, on="AdminComment", how="left")
    result["TopSubnet24Records"] = pd.to_numeric(
        result["TopSubnet24Records"], errors="coerce"
    ).fillna(0)
    result["TopSubnet24CoverageFromTotalRecordsPercent"] = safe_percent(
        result["TopSubnet24Records"], result["TotalRecords"]
    )
    result["TopSubnet24CoverageFromValidSubnet24RecordsPercent"] = safe_percent(
        result["TopSubnet24Records"], result["RecordsWithSubnet24"]
    )
    result["Subnet24Score"] = 0

    sufficient_subnet24_evidence = (
        (result["RecordsWithSubnet24"] >= MIN_VALID_SUBNET24_RECORDS)
        & (
            result["Subnet24DataCompletenessPercent"]
            >= MIN_VALID_SUBNET24_DATA_COVERAGE_PERCENT
        )
    )
    result.loc[sufficient_subnet24_evidence, "Subnet24Score"] = (
        result.loc[
            sufficient_subnet24_evidence,
            "TopSubnet24CoverageFromValidSubnet24RecordsPercent",
        ].map(subnet24_score)
    )
    result["Subnet24Priority"] = result["Subnet24Score"].map(subnet24_priority)
    result["Subnet24EvidenceDecision"] = "INSUFFICIENT SUBNET24 EVIDENCE"
    result["Subnet24ScoreReason"] = "Insufficient subnet evidence"

    low_concentration = (
        sufficient_subnet24_evidence
        & (result["Subnet24Score"] == SUBNET24_SCORE_1)
    )
    moderate_concentration = sufficient_subnet24_evidence & result[
        "Subnet24Score"
    ].isin([SUBNET24_SCORE_2, SUBNET24_SCORE_3])
    high_concentration = sufficient_subnet24_evidence & result[
        "Subnet24Score"
    ].isin([SUBNET24_SCORE_4, SUBNET24_SCORE_5])
    very_high_concentration = (
        sufficient_subnet24_evidence
        & (result["Subnet24Score"] == SUBNET24_SCORE_6)
    )

    result.loc[
        low_concentration,
        ["Subnet24EvidenceDecision", "Subnet24ScoreReason"],
    ] = ["LOW /24 CONCENTRATION", "Low /24 concentration"]
    result.loc[
        moderate_concentration,
        ["Subnet24EvidenceDecision", "Subnet24ScoreReason"],
    ] = ["MODERATE /24 CONCENTRATION", "Moderate /24 concentration"]
    result.loc[
        high_concentration,
        ["Subnet24EvidenceDecision", "Subnet24ScoreReason"],
    ] = ["HIGH /24 CONCENTRATION", "High /24 concentration"]
    result.loc[
        very_high_concentration,
        ["Subnet24EvidenceDecision", "Subnet24ScoreReason"],
    ] = ["VERY HIGH /24 CONCENTRATION", "Very high /24 concentration"]

    result = normalize_count_columns(
        result,
        [
            "TotalRecords",
            "RecordsWithSubnet24",
            "UniqueSubnet24",
            "TopSubnet24Records",
            "Subnet24Score",
        ],
    )
    return (
        result.sort_values(
            by=[
                "Subnet24Score",
                "TopSubnet24CoverageFromValidSubnet24RecordsPercent",
                "TopSubnet24Records",
                "TotalRecords",
            ],
            ascending=[False, False, False, False],
        )
        .loc[:, SUBNET24_ANALYSIS_COLUMNS]
    )
