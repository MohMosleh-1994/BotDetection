"""Build final BotDetection reports from analysis CSV outputs."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


PER_UA_FILES = {
    "candidate": "Candidate_Summary.csv",
    "time": "Time_Analysis.csv",
    "ip": "PerUA_IP_Analysis.csv",
    "subnet24": "PerUA_Subnet24_Analysis.csv",
    "ua": "UA_Structure_Analysis.csv",
}

GLOBAL_FILES = {
    "GLOBAL_IP": "Global_IP_Analysis.csv",
    "GLOBAL_SUBNET24": "Global_Subnet24_Analysis.csv",
    "GLOBAL_SUBNET16": "Global_Subnet16_Analysis.csv",
}

SCORE_COLUMNS = [
    "TimeScore",
    "IPScore",
    "Subnet24Score",
    "UAStructureScore",
]

REVIEW_DECISIONS = {"REVIEW", "HIGH", "CRITICAL"}

FINAL_REPORT_COLUMNS = [
    "AdminComment",
    "RecordCount",
    "UniqueIPs",
    "UniqueSubnet24",
    "FirstSeenUtc",
    "LastSeenUtc",
    "ActiveMinutes",
    "PeakMinuteUtc",
    "PeakMinuteHits",
    "LocalMedianHits",
    "BurstScore",
    "TimeScore",
    "TimePriority",
    "TopIPAddress",
    "TopIPRecords",
    "TopIPCoverageFromValidIPRecordsPercent",
    "IPScore",
    "IPPriority",
    "IPScoreReason",
    "TopSubnet24",
    "TopSubnet24Records",
    "TopSubnet24CoverageFromValidSubnet24RecordsPercent",
    "Subnet24Score",
    "Subnet24EvidenceDecision",
    "BrowserFamily",
    "BrowserVersion",
    "OSFamily",
    "OSVersion",
    "DeviceFamily",
    "UAStructureDecision",
    "UAReason",
    "UAStructureScore",
    "SuspicionScore",
    "FinalDecision",
    "ScoreReasons",
]


@dataclass
class ScoringResult:
    """Summary returned by the report builder."""

    success: bool
    output_dir: Path
    rows_written: dict[str, int]
    warnings: list[str]
    errors: list[str]


def normalize_text(value: Any) -> str:
    """Return a stripped text value for audit strings."""
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def read_module_csv(output_dir: Path, filename: str, warnings: list[str]) -> pd.DataFrame:
    """Read one module CSV if it exists."""
    path = output_dir / filename
    if not path.exists():
        warnings.append(f"Missing input file: {filename}")
        return pd.DataFrame()

    try:
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    except pd.errors.EmptyDataError:
        warnings.append(f"Input file is empty: {filename}")
        return pd.DataFrame()


def select_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Return merge columns that exist, preserving AdminComment for joins."""
    if df.empty or "AdminComment" not in df.columns:
        return pd.DataFrame(columns=columns)
    return df.reindex(columns=columns)


def numeric_column(df: pd.DataFrame, column: str) -> pd.Series:
    """Return a numeric series with nulls converted to 0."""
    if column not in df.columns:
        return pd.Series([0] * len(df), index=df.index)
    return pd.to_numeric(df[column], errors="coerce").fillna(0)


def ensure_score_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Fill missing score columns with 0 without recreating module formulas."""
    for column in SCORE_COLUMNS:
        if column not in df.columns:
            df[column] = 0
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0).astype(int)
    return df


def final_decision(score: int) -> str:
    """Convert total score into the final review bucket."""
    if score <= 9:
        return "LOW"
    if score <= 19:
        return "REVIEW"
    if score <= 29:
        return "HIGH"
    return "CRITICAL"


def reason_value(row: pd.Series, *columns: str, fallback: str = "MISSING") -> str:
    """Pick the first non-empty audit value from a row."""
    for column in columns:
        value = normalize_text(row.get(column))
        if value:
            return value
    return fallback


def build_score_reasons(row: pd.Series) -> str:
    """Describe how the final score was assembled."""
    return (
        f"Time={reason_value(row, 'TimePriority')}({int(row['TimeScore'])}); "
        f"IP={reason_value(row, 'IPPriority')}({int(row['IPScore'])}); "
        f"Subnet24={reason_value(row, 'Subnet24EvidenceDecision')}({int(row['Subnet24Score'])}); "
        f"UA={reason_value(row, 'UAStructureDecision')}({int(row['UAStructureScore'])})"
    )


def build_fallback_candidate_list(inputs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Build an AdminComment list from available per-UA outputs if needed."""
    admin_comments: list[pd.Series] = []
    for df in inputs.values():
        if not df.empty and "AdminComment" in df.columns:
            admin_comments.append(df["AdminComment"])

    if not admin_comments:
        return pd.DataFrame(columns=["AdminComment"])

    return (
        pd.concat(admin_comments, ignore_index=True)
        .dropna()
        .drop_duplicates()
        .to_frame(name="AdminComment")
    )


def sort_report(df: pd.DataFrame) -> pd.DataFrame:
    """Sort the final report by score and the strongest supporting metrics."""
    sort_columns = [
        "SuspicionScore",
        "RecordCount",
        "TimeScore",
        "IPScore",
        "Subnet24Score",
        "UAStructureScore",
    ]
    for column in sort_columns:
        df[f"_Sort_{column}"] = numeric_column(df, column)

    helper_columns = [f"_Sort_{column}" for column in sort_columns]
    return (
        df.sort_values(by=helper_columns, ascending=[False] * len(helper_columns))
        .drop(columns=helper_columns)
        .reset_index(drop=True)
    )


def build_per_user_agent_reports(
    output_dir: Path,
    inputs: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Merge per-AdminComment module outputs and calculate final scores."""
    candidate = inputs["candidate"]
    if candidate.empty or "AdminComment" not in candidate.columns:
        final_report = build_fallback_candidate_list(inputs)
    else:
        final_report = candidate.copy()

    time_columns = [
        "AdminComment",
        "PeakMinuteUtc",
        "PeakMinuteHits",
        "LocalMedianHits",
        "BurstScore",
        "TimeScore",
        "TimePriority",
    ]
    ip_columns = [
        "AdminComment",
        "RecordsWithIP",
        "TopIPAddress",
        "TopIPRecords",
        "TopIPCoverageFromValidIPRecordsPercent",
        "IPScore",
        "IPPriority",
        "IPScoreReason",
    ]
    subnet24_columns = [
        "AdminComment",
        "RecordsWithSubnet24",
        "TopSubnet24",
        "TopSubnet24Records",
        "TopSubnet24CoverageFromValidSubnet24RecordsPercent",
        "Subnet24Score",
        "Subnet24EvidenceDecision",
    ]
    ua_columns = [
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

    merge_specs = [
        (inputs["time"], time_columns),
        (inputs["ip"], ip_columns),
        (inputs["subnet24"], subnet24_columns),
        (inputs["ua"], ua_columns),
    ]

    for df, columns in merge_specs:
        final_report = final_report.merge(
            select_columns(df, columns),
            on="AdminComment",
            how="left",
        )

    final_report = ensure_score_columns(final_report)
    final_report["SuspicionScore"] = final_report[SCORE_COLUMNS].sum(axis=1)
    final_report["FinalDecision"] = final_report["SuspicionScore"].map(final_decision)
    final_report["ScoreReasons"] = final_report.apply(build_score_reasons, axis=1)
    final_report = sort_report(final_report)
    final_report = final_report.reindex(columns=FINAL_REPORT_COLUMNS)

    review_queue = final_report.loc[
        final_report["FinalDecision"].isin(REVIEW_DECISIONS)
    ].copy()

    final_report.to_csv(output_dir / "Final_Suspicious_Report.csv", index=False, encoding="utf-8")
    review_queue.to_csv(output_dir / "Final_Review_Queue.csv", index=False, encoding="utf-8")
    return final_report, review_queue


def build_global_report(output_dir: Path, warnings: list[str]) -> pd.DataFrame:
    """Append independent global analysis outputs into one investigation report."""
    frames: list[pd.DataFrame] = []

    for analysis_type, filename in GLOBAL_FILES.items():
        df = read_module_csv(output_dir, filename, warnings)
        if df.empty:
            continue
        df = df.copy()
        df.insert(0, "AnalysisType", analysis_type)
        frames.append(df)

    if frames:
        all_columns: list[str] = []
        for frame in frames:
            for column in frame.columns:
                if column not in all_columns:
                    all_columns.append(column)
        report = pd.concat(
            [frame.reindex(columns=all_columns) for frame in frames],
            ignore_index=True,
        )
    else:
        report = pd.DataFrame(columns=["AnalysisType"])

    if "RecordCount" in report.columns:
        report["_SortRecordCount"] = numeric_column(report, "RecordCount")
        report["_SortDistinctAdminComments"] = numeric_column(report, "DistinctAdminComments")
        report = (
            report.sort_values(
                by=["AnalysisType", "_SortRecordCount", "_SortDistinctAdminComments"],
                ascending=[True, False, False],
            )
            .drop(columns=["_SortRecordCount", "_SortDistinctAdminComments"])
            .reset_index(drop=True)
        )

    report.to_csv(output_dir / "Global_Investigation_Report.csv", index=False, encoding="utf-8")
    return report


def build_reports(output_dir: Path | str) -> ScoringResult:
    """Build final per-UA and global reports from one output folder."""
    resolved_output_dir = Path(output_dir)
    warnings: list[str] = []
    errors: list[str] = []
    rows_written: dict[str, int] = {}

    if not resolved_output_dir.exists() or not resolved_output_dir.is_dir():
        return ScoringResult(
            success=False,
            output_dir=resolved_output_dir,
            rows_written=rows_written,
            warnings=warnings,
            errors=[f"Output folder does not exist: {resolved_output_dir}"],
        )

    inputs = {
        name: read_module_csv(resolved_output_dir, filename, warnings)
        for name, filename in PER_UA_FILES.items()
    }

    try:
        final_report, review_queue = build_per_user_agent_reports(resolved_output_dir, inputs)
        rows_written["Final_Suspicious_Report.csv"] = len(final_report)
        rows_written["Final_Review_Queue.csv"] = len(review_queue)
    except Exception as exc:
        errors.append(f"Per-User-Agent scoring failed: {exc}")

    try:
        global_report = build_global_report(resolved_output_dir, warnings)
        rows_written["Global_Investigation_Report.csv"] = len(global_report)
    except Exception as exc:
        errors.append(f"Global investigation report failed: {exc}")

    return ScoringResult(
        success=not errors,
        output_dir=resolved_output_dir,
        rows_written=rows_written,
        warnings=warnings,
        errors=errors,
    )


def main(argv: list[str]) -> int:
    """CLI entry point for standalone scoring report generation."""
    if len(argv) != 2:
        print('Usage: python Python/build_scoring_reports.py "Output/2026-07-16_123800"', file=sys.stderr)
        return 2

    result = build_reports(Path(argv[1]))
    print(f"Output folder: {result.output_dir}")
    for filename, row_count in result.rows_written.items():
        print(f"{filename}: {row_count} row(s)")

    if result.warnings:
        print("Warnings:")
        for warning in result.warnings:
            print(f"- {warning}")

    if result.errors:
        print("Errors:", file=sys.stderr)
        for error in result.errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
