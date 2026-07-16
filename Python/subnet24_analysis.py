"""Run in-memory per-User-Agent /24 subnet concentration analysis."""

from __future__ import annotations

import pandas as pd

from pipeline_common import normalize_count_columns, safe_percent


SUBNET24_SCORE_BY_DECISION = {
    "WORTH CHECKING": 10,
    "LOW /24 CONCENTRATION": 5,
    "LOW EVIDENCE": 0,
}

SUBNET24_ANALYSIS_COLUMNS = [
    "AdminComment",
    "TotalRecords",
    "RecordsWithSubnet24",
    "UniqueSubnet24",
    "TopSubnet24",
    "TopSubnet24Records",
    "TopSubnet24CoverageFromTotalRecordsPercent",
    "TopSubnet24CoverageFromValidSubnet24RecordsPercent",
    "Subnet24EvidenceDecision",
    "Subnet24Score",
]


def subnet24_decision(row: pd.Series) -> str:
    """Assign the /24 concentration evidence label."""
    if row["TotalRecords"] < 100 and row["UniqueSubnet24"] < 100:
        return "LOW EVIDENCE"
    if row["TopSubnet24CoverageFromValidSubnet24RecordsPercent"] >= 20:
        return "WORTH CHECKING"
    return "LOW /24 CONCENTRATION"


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
    result["Subnet24EvidenceDecision"] = result.apply(subnet24_decision, axis=1)
    result["Subnet24Score"] = (
        result["Subnet24EvidenceDecision"].map(SUBNET24_SCORE_BY_DECISION).fillna(0)
    )

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
    decision_priority = {"WORTH CHECKING": 1, "LOW /24 CONCENTRATION": 2, "LOW EVIDENCE": 3}
    result["_DecisionPriority"] = result["Subnet24EvidenceDecision"].map(decision_priority).fillna(4)
    return (
        result.sort_values(
            by=["_DecisionPriority", "TopSubnet24CoverageFromValidSubnet24RecordsPercent"],
            ascending=[True, False],
        )
        .drop(columns=["_DecisionPriority"])
        .loc[:, SUBNET24_ANALYSIS_COLUMNS]
    )
