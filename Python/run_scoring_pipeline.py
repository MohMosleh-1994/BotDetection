"""Run the local BotDetection scoring pipeline from one Results CSV export."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from ua_csv_analysis import (
    AnalysisError as CsvAnalysisError,
    is_null_or_empty,
    is_unknown,
    normalize_text,
    parse_user_agent,
    read_csv_with_fallback,
)


WINDOW_MINUTES = 5

INVALID_IP_VALUES = {"", "NULL", "N/A", "NA", "-"}
INVALID_SUBNET24_VALUES = {"", "NULL", "N/A", "NA", "-", "."}
INVALID_RECORD_COUNT_VALUES = {"", "NULL", "N/A", "NA", "-", "OTHER", "UNKNOWN"}

TIME_SCORE_BY_DECISION = {
    "WORTH CHECKING": 40,
    "LOW BURST": 15,
    "LOW EVIDENCE": 0,
}
IP_SCORE_BY_DECISION = {
    "WORTH CHECKING": 25,
    "LOW IP CONCENTRATION": 10,
    "LOW EVIDENCE": 0,
}
SUBNET24_SCORE_BY_DECISION = {
    "WORTH CHECKING": 10,
    "LOW /24 CONCENTRATION": 5,
    "LOW EVIDENCE": 0,
}
UA_SCORE_BY_DECISION = {
    "WORTH CHECKING": 10,
    "PARTIAL": 5,
    "COMPLETE": 0,
}

CANDIDATE_SUMMARY_COLUMNS = [
    "AdminComment",
    "RecordCount",
    "UniqueIPs",
    "UniqueSubnet24",
    "FirstSeenUtc",
    "LastSeenUtc",
    "ActiveMinutes",
    "VolumeScore",
]

TIME_ANALYSIS_COLUMNS = [
    "AdminComment",
    "TotalRecords",
    "RecordsWithValidDate",
    "PeakMinuteUtc",
    "PeakMinuteHits",
    "LocalMedianHits",
    "BurstScore",
    "TimeDecision",
    "TimeScore",
]

IP_ANALYSIS_COLUMNS = [
    "AdminComment",
    "TotalRecords",
    "RecordsWithIP",
    "UniqueIPs",
    "TopIPAddress",
    "TopIPRecords",
    "TopIPCoverageFromTotalRecordsPercent",
    "TopIPCoverageFromValidIPRecordsPercent",
    "IPEvidenceDecision",
    "IPScore",
]

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

UA_STRUCTURE_COLUMNS = [
    "AdminComment",
    "BrowserFamily",
    "BrowserVersion",
    "OSFamily",
    "OSVersion",
    "DeviceFamily",
    "UAStructureDecision",
    "UAReason",
    "UAStructureScore",
]

FINAL_REPORT_COLUMNS = [
    "AdminComment",
    "RecordCount",
    "UniqueIPs",
    "UniqueSubnet24",
    "FirstSeenUtc",
    "LastSeenUtc",
    "ActiveMinutes",
    "TimeDecision",
    "PeakMinuteUtc",
    "PeakMinuteHits",
    "LocalMedianHits",
    "BurstScore",
    "TimeScore",
    "IPEvidenceDecision",
    "TopIPAddress",
    "TopIPRecords",
    "TopIPCoverageFromValidIPRecordsPercent",
    "IPScore",
    "Subnet24EvidenceDecision",
    "TopSubnet24",
    "TopSubnet24Records",
    "TopSubnet24CoverageFromValidSubnet24RecordsPercent",
    "Subnet24Score",
    "UAStructureDecision",
    "UAReason",
    "BrowserFamily",
    "BrowserVersion",
    "OSFamily",
    "OSVersion",
    "DeviceFamily",
    "UAStructureScore",
    "VolumeScore",
    "SuspicionScore",
    "FinalDecision",
    "ScoreReasons",
]


class PipelineError(Exception):
    """Raised when the scoring pipeline cannot continue."""


@dataclass
class PreparedInput:
    """Normalized input data and audit details."""

    rows: pd.DataFrame
    total_original_rows: int
    skipped_admin_comment_rows: int
    warnings: list[str]


@dataclass
class ModuleStatus:
    """Status for one pipeline module."""

    name: str
    filename: str
    success: bool
    rows_written: int = 0
    error: str = ""


def normalize_column_key(column_name: Any) -> str:
    """Normalize a column name for case-insensitive matching."""
    return str(column_name).lstrip("\ufeff").strip().casefold()


def find_column(columns: list[str], candidates: list[str]) -> str | None:
    """Find the first matching input column using case-insensitive names."""
    by_key: dict[str, str] = {}
    for column in columns:
        by_key.setdefault(normalize_column_key(column), column)

    for candidate in candidates:
        match = by_key.get(normalize_column_key(candidate))
        if match is not None:
            return match
    return None


def safe_percent(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """Calculate percentage while returning 0 when the denominator is 0."""
    denominator = denominator.where(denominator != 0)
    return (numerator * 100.0 / denominator).fillna(0).round(2)


def safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """Calculate a ratio while preserving missing values for missing denominators."""
    denominator = denominator.where(denominator != 0)
    return (numerator / denominator).round(2)


def normalize_count_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Format count-like columns as nullable integers when present."""
    for column in columns:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce").round(0).astype("Int64")
    return df


def normalize_invalid_text(value: Any, invalid_values: set[str]) -> str | pd.NA:
    """Return a trimmed value or NA when the value is invalid for analysis."""
    text_value = normalize_text(value)
    if text_value.upper() in invalid_values:
        return pd.NA
    return text_value


def normalize_ip_address(value: Any) -> str | pd.NA:
    """Use only the first comma-separated IP and remove invalid values."""
    first_ip = normalize_text(value).split(",", 1)[0].strip()
    if first_ip.upper() in INVALID_IP_VALUES:
        return pd.NA
    return first_ip


def load_and_prepare_results(input_path: Path) -> PreparedInput:
    """Read Results.csv once, normalize columns, and prepare reusable fields."""
    try:
        raw_df = read_csv_with_fallback(input_path)
    except CsvAnalysisError as exc:
        raise PipelineError(str(exc)) from exc

    warnings: list[str] = []
    total_original_rows = len(raw_df)
    columns = list(raw_df.columns)

    required_columns = {
        "AdminComment": ["AdminComment"],
        "IPAddress": ["IPAddress"],
        "CreatedOnUtc": ["CreatedOnUtc"],
        "RangeSubnet24": ["RangeSubnet24", "RangesSubnet24"],
    }

    selected_columns: dict[str, str] = {}
    missing_required: list[str] = []
    for canonical_name, aliases in required_columns.items():
        matched_column = find_column(columns, aliases)
        if matched_column is None:
            missing_required.append(" or ".join(aliases))
        else:
            selected_columns[canonical_name] = matched_column

    if missing_required:
        raise PipelineError(
            "Input CSV is missing required column(s): " + ", ".join(missing_required)
        )

    optional_columns = {
        "CleanAdminComment": ["CleanAdminComment"],
        "RecordCount": ["RecordCount"],
    }
    for canonical_name, aliases in optional_columns.items():
        matched_column = find_column(columns, aliases)
        if matched_column is not None:
            selected_columns[canonical_name] = matched_column

    if selected_columns["RangeSubnet24"] != "RangeSubnet24":
        warnings.append(
            f"Using {selected_columns['RangeSubnet24']} as the internal RangeSubnet24 column."
        )

    working = pd.DataFrame()
    for canonical_name, source_name in selected_columns.items():
        working[canonical_name] = raw_df[source_name]

    if "CleanAdminComment" not in working.columns:
        working["CleanAdminComment"] = ""

    working["AdminComment"] = working["AdminComment"].map(normalize_text)
    valid_admin_comment = ~working["AdminComment"].map(is_null_or_empty)
    skipped_admin_comment_rows = int((~valid_admin_comment).sum())
    working = working.loc[valid_admin_comment].copy().reset_index(drop=True)

    if "RecordCount" in working.columns:
        raw_counts = working["RecordCount"].map(normalize_text)
        missing_counts = raw_counts.str.upper().isin(INVALID_RECORD_COUNT_VALUES)
        numeric_counts = pd.to_numeric(raw_counts.mask(missing_counts, "0"), errors="coerce")
        invalid_counts = int(numeric_counts.isna().sum())
        if invalid_counts:
            warnings.append(
                f"RecordCount had {invalid_counts} non-numeric value(s); those rows use weight 0."
            )
        working["_RecordWeight"] = numeric_counts.fillna(0).astype(float)
    else:
        working["RecordCount"] = "1"
        working["_RecordWeight"] = 1.0

    working["CleanAdminComment"] = working["CleanAdminComment"].map(normalize_text)
    working["IPAddress"] = working["IPAddress"].map(normalize_text)
    working["RangeSubnet24"] = working["RangeSubnet24"].map(normalize_text)
    working["CreatedOnUtc"] = working["CreatedOnUtc"].map(normalize_text)

    working["ValidIPAddress"] = working["IPAddress"].map(normalize_ip_address)
    working["ValidSubnet24"] = working["RangeSubnet24"].map(
        lambda value: normalize_invalid_text(value, INVALID_SUBNET24_VALUES)
    )
    working["CreatedOnUtcDate"] = pd.to_datetime(working["CreatedOnUtc"], errors="coerce")

    invalid_date_rows = int(working["CreatedOnUtcDate"].isna().sum())
    if invalid_date_rows:
        warnings.append(
            f"CreatedOnUtc had {invalid_date_rows} invalid or empty value(s); time fields ignore them."
        )

    return PreparedInput(
        rows=working,
        total_original_rows=total_original_rows,
        skipped_admin_comment_rows=skipped_admin_comment_rows,
        warnings=warnings,
    )


def volume_score(record_count: float) -> int:
    """Score traffic volume based on the required record-count bands."""
    if record_count < 100:
        return 0
    if record_count < 500:
        return 3
    if record_count < 2000:
        return 6
    if record_count < 10000:
        return 9
    if record_count < 40000:
        return 12
    return 15


def build_candidate_summary(rows: pd.DataFrame) -> pd.DataFrame:
    """Build per-AdminComment volume and date coverage summary."""
    if rows.empty:
        return pd.DataFrame(columns=CANDIDATE_SUMMARY_COLUMNS)

    summary = (
        rows.groupby("AdminComment", dropna=False, sort=False)
        .agg(
            RecordCount=("_RecordWeight", "sum"),
            UniqueIPs=("ValidIPAddress", "nunique"),
            UniqueSubnet24=("ValidSubnet24", "nunique"),
            FirstSeenUtc=("CreatedOnUtcDate", "min"),
            LastSeenUtc=("CreatedOnUtcDate", "max"),
        )
        .reset_index()
    )

    summary["ActiveMinutes"] = (
        (summary["LastSeenUtc"] - summary["FirstSeenUtc"]).dt.total_seconds() / 60.0
    ).round(2)
    summary.loc[summary["FirstSeenUtc"].isna() | summary["LastSeenUtc"].isna(), "ActiveMinutes"] = pd.NA
    summary["VolumeScore"] = summary["RecordCount"].map(volume_score)

    summary = normalize_count_columns(summary, ["RecordCount", "UniqueIPs", "UniqueSubnet24", "VolumeScore"])
    return summary[CANDIDATE_SUMMARY_COLUMNS].sort_values(
        by=["RecordCount", "UniqueIPs", "UniqueSubnet24"],
        ascending=[False, False, False],
    )


def build_time_analysis(rows: pd.DataFrame) -> pd.DataFrame:
    """Reproduce the current minute-level burst analysis for every AdminComment."""
    if rows.empty:
        return pd.DataFrame(columns=TIME_ANALYSIS_COLUMNS)

    working = rows[["AdminComment", "_RecordWeight", "CreatedOnUtcDate"]].copy()
    working["ValidDateWeight"] = working["_RecordWeight"].where(
        working["CreatedOnUtcDate"].notna(), 0
    )

    totals = (
        working.groupby("AdminComment", dropna=False, sort=False)
        .agg(
            TotalRecords=("_RecordWeight", "sum"),
            RecordsWithValidDate=("ValidDateWeight", "sum"),
        )
        .reset_index()
    )

    valid_dates = working.loc[working["CreatedOnUtcDate"].notna()].copy()
    if not valid_dates.empty:
        valid_dates["MinuteUtc"] = valid_dates["CreatedOnUtcDate"].dt.floor("min")
        minute_hits = (
            valid_dates.groupby(["AdminComment", "MinuteUtc"], dropna=False, sort=False)[
                "_RecordWeight"
            ]
            .sum()
            .reset_index(name="Hits")
        )

        peak = (
            minute_hits.sort_values(
                by=["AdminComment", "Hits", "MinuteUtc"],
                ascending=[True, False, True],
            )
            .drop_duplicates(subset=["AdminComment"], keep="first")
            .rename(columns={"MinuteUtc": "PeakMinuteUtc", "Hits": "PeakMinuteHits"})
        )

        local_window = minute_hits.merge(
            peak[["AdminComment", "PeakMinuteUtc", "PeakMinuteHits"]],
            on="AdminComment",
            how="inner",
        )
        window_start = local_window["PeakMinuteUtc"] - pd.Timedelta(minutes=WINDOW_MINUTES)
        window_end = local_window["PeakMinuteUtc"] + pd.Timedelta(minutes=WINDOW_MINUTES)
        local_window = local_window.loc[
            (local_window["MinuteUtc"] >= window_start)
            & (local_window["MinuteUtc"] <= window_end)
        ]

        median = (
            local_window.groupby(
                ["AdminComment", "PeakMinuteUtc", "PeakMinuteHits"],
                dropna=False,
                sort=False,
            )["Hits"]
            .median()
            .reset_index(name="LocalMedianHits")
        )
    else:
        median = pd.DataFrame(
            columns=["AdminComment", "PeakMinuteUtc", "PeakMinuteHits", "LocalMedianHits"]
        )

    result = totals.merge(median, on="AdminComment", how="left")
    result["BurstScore"] = safe_ratio(result["PeakMinuteHits"], result["LocalMedianHits"])

    result["TimeDecision"] = "LOW BURST"
    result.loc[result["TotalRecords"] < 100, "TimeDecision"] = "LOW EVIDENCE"
    worth_checking = (
        (result["TotalRecords"] >= 100)
        & (result["PeakMinuteHits"] >= 100)
        & (result["BurstScore"] >= 20)
    )
    result.loc[worth_checking, "TimeDecision"] = "WORTH CHECKING"
    result["TimeScore"] = result["TimeDecision"].map(TIME_SCORE_BY_DECISION).fillna(0)

    result = normalize_count_columns(
        result,
        ["TotalRecords", "RecordsWithValidDate", "PeakMinuteHits", "TimeScore"],
    )
    result["LocalMedianHits"] = pd.to_numeric(result["LocalMedianHits"], errors="coerce").round(2)
    result["BurstScore"] = pd.to_numeric(result["BurstScore"], errors="coerce").round(2)

    decision_priority = {"WORTH CHECKING": 1, "LOW BURST": 2, "LOW EVIDENCE": 3}
    result["_DecisionPriority"] = result["TimeDecision"].map(decision_priority).fillna(4)
    result = result.sort_values(
        by=["_DecisionPriority", "BurstScore", "PeakMinuteHits", "TotalRecords"],
        ascending=[True, False, False, False],
    ).drop(columns=["_DecisionPriority"])

    return result[TIME_ANALYSIS_COLUMNS]


def build_ip_analysis(rows: pd.DataFrame) -> pd.DataFrame:
    """Calculate per-AdminComment IP concentration using first-IP normalization."""
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

    result["IPEvidenceDecision"] = "LOW IP CONCENTRATION"
    low_evidence = (result["TotalRecords"] < 100) & (result["UniqueIPs"] < 100)
    result.loc[low_evidence, "IPEvidenceDecision"] = "LOW EVIDENCE"
    result.loc[
        (~low_evidence) & (result["TopIPCoverageFromValidIPRecordsPercent"] >= 20),
        "IPEvidenceDecision",
    ] = "WORTH CHECKING"
    result["IPScore"] = result["IPEvidenceDecision"].map(IP_SCORE_BY_DECISION).fillna(0)

    result = normalize_count_columns(
        result,
        ["TotalRecords", "RecordsWithIP", "UniqueIPs", "TopIPRecords", "IPScore"],
    )

    decision_priority = {"WORTH CHECKING": 1, "LOW IP CONCENTRATION": 2, "LOW EVIDENCE": 3}
    result["_DecisionPriority"] = result["IPEvidenceDecision"].map(decision_priority).fillna(4)
    result = result.sort_values(
        by=["_DecisionPriority", "TopIPCoverageFromValidIPRecordsPercent"],
        ascending=[True, False],
    ).drop(columns=["_DecisionPriority"])

    return result[IP_ANALYSIS_COLUMNS]


def build_subnet24_analysis(rows: pd.DataFrame) -> pd.DataFrame:
    """Calculate per-AdminComment /24 subnet concentration."""
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

    result["Subnet24EvidenceDecision"] = "LOW /24 CONCENTRATION"
    low_evidence = (result["TotalRecords"] < 100) & (result["UniqueSubnet24"] < 100)
    result.loc[low_evidence, "Subnet24EvidenceDecision"] = "LOW EVIDENCE"
    result.loc[
        (~low_evidence) & (result["TopSubnet24CoverageFromValidSubnet24RecordsPercent"] >= 20),
        "Subnet24EvidenceDecision",
    ] = "WORTH CHECKING"
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
    result = result.sort_values(
        by=["_DecisionPriority", "TopSubnet24CoverageFromValidSubnet24RecordsPercent"],
        ascending=[True, False],
    ).drop(columns=["_DecisionPriority"])

    return result[SUBNET24_ANALYSIS_COLUMNS]


def build_ua_reason(parsed_fields: dict[str, Any]) -> str:
    """Explain which structural User-Agent fields are missing."""
    missing_fields: list[str] = []
    if is_unknown(parsed_fields.get("BrowserFamily")):
        missing_fields.append("BrowserFamily")
    if is_unknown(parsed_fields.get("BrowserVersion")):
        missing_fields.append("BrowserVersion")
    if is_unknown(parsed_fields.get("OSFamily")):
        missing_fields.append("OSFamily")

    if not missing_fields:
        return "Browser family, browser version, and OS family are available."
    return "Missing: " + ", ".join(missing_fields)


def build_ua_structure_analysis(rows: pd.DataFrame) -> pd.DataFrame:
    """Parse every distinct AdminComment and score structural completeness only."""
    if rows.empty:
        return pd.DataFrame(columns=UA_STRUCTURE_COLUMNS)

    unique_admin_comments = rows[["AdminComment"]].drop_duplicates(ignore_index=True)
    parsed_rows: list[dict[str, Any]] = []

    for admin_comment in unique_admin_comments["AdminComment"]:
        parsed_fields = parse_user_agent(admin_comment)
        decision = parsed_fields["StructureDecision"]
        parsed_rows.append(
            {
                "AdminComment": admin_comment,
                "BrowserFamily": parsed_fields["BrowserFamily"],
                "BrowserVersion": parsed_fields["BrowserVersion"],
                "OSFamily": parsed_fields["OSFamily"],
                "OSVersion": parsed_fields["OSVersion"],
                "DeviceFamily": parsed_fields["DeviceFamily"],
                "UAStructureDecision": decision,
                "UAReason": build_ua_reason(parsed_fields),
                "UAStructureScore": UA_SCORE_BY_DECISION.get(decision, 0),
            }
        )

    result = pd.DataFrame(parsed_rows)
    result = normalize_count_columns(result, ["UAStructureScore"])
    return result[UA_STRUCTURE_COLUMNS].sort_values(
        by=["UAStructureScore", "AdminComment"],
        ascending=[False, True],
    )


def create_output_dir(project_root: Path, run_start: datetime) -> Path:
    """Create a timestamped output directory without overwriting previous runs."""
    output_root = project_root / "Output"
    output_root.mkdir(parents=True, exist_ok=True)

    base_name = run_start.strftime("%Y-%m-%d_%H%M%S")
    output_dir = output_root / base_name
    counter = 1
    while output_dir.exists():
        output_dir = output_root / f"{base_name}_{counter}"
        counter += 1
    output_dir.mkdir(parents=True)
    return output_dir


def write_dataframe(df: pd.DataFrame, output_dir: Path, filename: str) -> None:
    """Write a dataframe as UTF-8 CSV."""
    df.to_csv(output_dir / filename, index=False, encoding="utf-8")


def run_module(
    name: str,
    filename: str,
    rows: pd.DataFrame,
    output_dir: Path,
    statuses: list[ModuleStatus],
    errors: list[str],
    builder: Callable[[pd.DataFrame], pd.DataFrame],
) -> pd.DataFrame:
    """Run one analysis module, save its output, and capture failures."""
    try:
        result = builder(rows)
        write_dataframe(result, output_dir, filename)
        statuses.append(
            ModuleStatus(name=name, filename=filename, success=True, rows_written=len(result))
        )
        return result
    except Exception as exc:  # Keep the rest of the pipeline running for auditability.
        error_message = f"{name} failed: {exc}"
        errors.append(error_message)
        statuses.append(
            ModuleStatus(name=name, filename=filename, success=False, error=str(exc))
        )
        return pd.DataFrame()


def select_module_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Return only the requested columns, preserving an empty mergeable frame."""
    if df.empty or "AdminComment" not in df.columns:
        return pd.DataFrame(columns=columns)
    return df.reindex(columns=columns)


def build_candidate_fallback(rows: pd.DataFrame) -> pd.DataFrame:
    """Build a minimal AdminComment list if Candidate Summary unexpectedly fails."""
    if rows.empty:
        return pd.DataFrame(columns=CANDIDATE_SUMMARY_COLUMNS)

    fallback = (
        rows.groupby("AdminComment", dropna=False, sort=False)
        .agg(
            RecordCount=("_RecordWeight", "sum"),
            UniqueIPs=("ValidIPAddress", "nunique"),
            UniqueSubnet24=("ValidSubnet24", "nunique"),
        )
        .reset_index()
    )
    fallback["FirstSeenUtc"] = pd.NA
    fallback["LastSeenUtc"] = pd.NA
    fallback["ActiveMinutes"] = pd.NA
    fallback["VolumeScore"] = fallback["RecordCount"].map(volume_score)
    fallback = normalize_count_columns(
        fallback, ["RecordCount", "UniqueIPs", "UniqueSubnet24", "VolumeScore"]
    )
    return fallback[CANDIDATE_SUMMARY_COLUMNS]


def score_reason_value(value: Any, fallback: str = "MISSING") -> str:
    """Format a decision value for ScoreReasons."""
    text_value = normalize_text(value)
    return text_value if text_value else fallback


def final_decision(score: int) -> str:
    """Convert the numeric suspicion score into the final review bucket."""
    if score <= 24:
        return "LOW"
    if score <= 49:
        return "REVIEW"
    if score <= 74:
        return "HIGH"
    return "CRITICAL"


def build_score_reasons(row: pd.Series) -> str:
    """Build the final audit string showing which modules contributed points."""
    return (
        f"Time={score_reason_value(row.get('TimeDecision'))}({int(row['TimeScore'])}); "
        f"IP={score_reason_value(row.get('IPEvidenceDecision'))}({int(row['IPScore'])}); "
        f"/24={score_reason_value(row.get('Subnet24EvidenceDecision'))}"
        f"({int(row['Subnet24Score'])}); "
        f"Volume={int(row['VolumeScore'])}; "
        f"UA={score_reason_value(row.get('UAStructureDecision'))}"
        f"({int(row['UAStructureScore'])})"
    )


def build_final_reports(
    rows: pd.DataFrame,
    candidate_summary: pd.DataFrame,
    time_analysis: pd.DataFrame,
    ip_analysis: pd.DataFrame,
    subnet24_analysis: pd.DataFrame,
    ua_structure: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Merge all per-AdminComment outputs and calculate the final score."""
    final_report = candidate_summary.copy()
    if final_report.empty and not rows.empty:
        final_report = build_candidate_fallback(rows)

    time_columns = [
        "AdminComment",
        "TimeDecision",
        "PeakMinuteUtc",
        "PeakMinuteHits",
        "LocalMedianHits",
        "BurstScore",
        "TimeScore",
    ]
    ip_columns = [
        "AdminComment",
        "IPEvidenceDecision",
        "TopIPAddress",
        "TopIPRecords",
        "TopIPCoverageFromValidIPRecordsPercent",
        "IPScore",
    ]
    subnet_columns = [
        "AdminComment",
        "Subnet24EvidenceDecision",
        "TopSubnet24",
        "TopSubnet24Records",
        "TopSubnet24CoverageFromValidSubnet24RecordsPercent",
        "Subnet24Score",
    ]

    final_report = final_report.merge(
        select_module_columns(time_analysis, time_columns),
        on="AdminComment",
        how="left",
    )
    final_report = final_report.merge(
        select_module_columns(ip_analysis, ip_columns),
        on="AdminComment",
        how="left",
    )
    final_report = final_report.merge(
        select_module_columns(subnet24_analysis, subnet_columns),
        on="AdminComment",
        how="left",
    )
    final_report = final_report.merge(
        select_module_columns(ua_structure, UA_STRUCTURE_COLUMNS),
        on="AdminComment",
        how="left",
    )

    score_columns = [
        "TimeScore",
        "IPScore",
        "Subnet24Score",
        "VolumeScore",
        "UAStructureScore",
    ]
    for column in score_columns:
        if column not in final_report.columns:
            final_report[column] = 0
        final_report[column] = pd.to_numeric(final_report[column], errors="coerce").fillna(0).astype(int)

    final_report["SuspicionScore"] = final_report[score_columns].sum(axis=1)
    final_report["FinalDecision"] = final_report["SuspicionScore"].map(final_decision)
    final_report["ScoreReasons"] = final_report.apply(build_score_reasons, axis=1)

    for column in FINAL_REPORT_COLUMNS:
        if column not in final_report.columns:
            final_report[column] = pd.NA

    sort_columns = [
        "SuspicionScore",
        "RecordCount",
        "BurstScore",
        "TopSubnet24CoverageFromValidSubnet24RecordsPercent",
        "TopIPCoverageFromValidIPRecordsPercent",
    ]
    for column in sort_columns:
        final_report[f"_Sort_{column}"] = pd.to_numeric(
            final_report[column], errors="coerce"
        ).fillna(0)

    sort_helper_columns = [f"_Sort_{column}" for column in sort_columns]
    final_report = (
        final_report.sort_values(by=sort_helper_columns, ascending=[False] * len(sort_helper_columns))
        .drop(columns=sort_helper_columns)
        .reset_index(drop=True)
    )

    final_report = final_report[FINAL_REPORT_COLUMNS]
    review_queue = final_report.loc[
        final_report["FinalDecision"].isin(["REVIEW", "HIGH", "CRITICAL"])
    ].copy()

    return final_report, review_queue


def write_run_summary(
    output_dir: Path,
    input_path: Path,
    run_start: datetime,
    run_end: datetime,
    prepared_input: PreparedInput | None,
    statuses: list[ModuleStatus],
    final_report: pd.DataFrame | None,
    warnings: list[str],
    errors: list[str],
) -> None:
    """Write a text summary for auditing the pipeline run."""
    decision_counts = {"LOW": 0, "REVIEW": 0, "HIGH": 0, "CRITICAL": 0}
    if final_report is not None and "FinalDecision" in final_report.columns:
        actual_counts = final_report["FinalDecision"].value_counts().to_dict()
        for decision in decision_counts:
            decision_counts[decision] = int(actual_counts.get(decision, 0))

    lines = [
        "BotDetection Scoring Pipeline Run Summary",
        "",
        f"Input file path: {input_path}",
        f"Run start time: {run_start.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Run end time: {run_end.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"Total original rows: {prepared_input.total_original_rows if prepared_input else 0}",
        (
            "Total distinct AdminComments: "
            f"{prepared_input.rows['AdminComment'].nunique() if prepared_input else 0}"
        ),
        (
            "Skipped rows: "
            f"{prepared_input.skipped_admin_comment_rows if prepared_input else 0} "
            "row(s) with null/empty/literal NULL AdminComment"
        ),
        "",
        "Module results:",
    ]

    if statuses:
        for status in statuses:
            state = "SUCCESS" if status.success else "FAILED"
            detail = f"{status.rows_written} row(s) written" if status.success else status.error
            lines.append(f"- {status.name} ({status.filename}): {state} - {detail}")
    else:
        lines.append("- No modules ran.")

    lines.extend(
        [
            "",
            f"LOW results: {decision_counts['LOW']}",
            f"REVIEW results: {decision_counts['REVIEW']}",
            f"HIGH results: {decision_counts['HIGH']}",
            f"CRITICAL results: {decision_counts['CRITICAL']}",
            "",
            "Warnings:",
        ]
    )
    lines.extend([f"- {warning}" for warning in warnings] or ["- None"])

    lines.append("")
    lines.append("Errors:")
    lines.extend([f"- {error}" for error in errors] or ["- None"])

    (output_dir / "Run_Summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_pipeline(input_path: Path) -> tuple[Path, bool]:
    """Execute the complete pipeline and return the output directory and success flag."""
    project_root = Path(__file__).resolve().parents[1]
    run_start = datetime.now()
    output_dir = create_output_dir(project_root, run_start)
    statuses: list[ModuleStatus] = []
    errors: list[str] = []
    warnings: list[str] = []
    prepared_input: PreparedInput | None = None
    final_report: pd.DataFrame | None = None

    try:
        prepared_input = load_and_prepare_results(input_path)
        warnings.extend(prepared_input.warnings)
        rows = prepared_input.rows
    except Exception as exc:
        errors.append(f"Input validation failed: {exc}")
        run_end = datetime.now()
        write_run_summary(
            output_dir,
            input_path,
            run_start,
            run_end,
            prepared_input,
            statuses,
            final_report,
            warnings,
            errors,
        )
        return output_dir, False

    candidate_summary = run_module(
        "Candidate Summary / Volume Analysis",
        "Candidate_Summary.csv",
        rows,
        output_dir,
        statuses,
        errors,
        build_candidate_summary,
    )
    time_analysis = run_module(
        "Time Analysis",
        "Time_Analysis.csv",
        rows,
        output_dir,
        statuses,
        errors,
        build_time_analysis,
    )
    ip_analysis = run_module(
        "Per-User-Agent IP Analysis",
        "PerUA_IP_Analysis.csv",
        rows,
        output_dir,
        statuses,
        errors,
        build_ip_analysis,
    )
    subnet24_analysis = run_module(
        "Per-User-Agent /24 Analysis",
        "PerUA_Subnet24_Analysis.csv",
        rows,
        output_dir,
        statuses,
        errors,
        build_subnet24_analysis,
    )
    ua_structure = run_module(
        "User-Agent Structure Analysis",
        "UA_Structure_Analysis.csv",
        rows,
        output_dir,
        statuses,
        errors,
        build_ua_structure_analysis,
    )

    try:
        final_report, review_queue = build_final_reports(
            rows,
            candidate_summary,
            time_analysis,
            ip_analysis,
            subnet24_analysis,
            ua_structure,
        )
        write_dataframe(final_report, output_dir, "Final_Suspicious_Report.csv")
        statuses.append(
            ModuleStatus(
                name="Final Suspicious Report",
                filename="Final_Suspicious_Report.csv",
                success=True,
                rows_written=len(final_report),
            )
        )
        write_dataframe(review_queue, output_dir, "Final_Review_Queue.csv")
        statuses.append(
            ModuleStatus(
                name="Final Review Queue",
                filename="Final_Review_Queue.csv",
                success=True,
                rows_written=len(review_queue),
            )
        )
    except Exception as exc:
        errors.append(f"Final report generation failed: {exc}")

    run_end = datetime.now()
    write_run_summary(
        output_dir,
        input_path,
        run_start,
        run_end,
        prepared_input,
        statuses,
        final_report,
        warnings,
        errors,
    )
    return output_dir, not errors


def main(argv: list[str]) -> int:
    """CLI entry point."""
    if len(argv) != 2:
        print(
            'Usage: python Python/run_scoring_pipeline.py "Data/Raw/Results.csv"',
            file=sys.stderr,
        )
        return 2

    output_dir, success = run_pipeline(Path(argv[1]))
    print(f"Output folder: {output_dir}")
    if not success:
        print("Pipeline finished with errors. Check Run_Summary.txt.", file=sys.stderr)
        return 1

    print("Pipeline finished successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
