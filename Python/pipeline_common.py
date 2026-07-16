"""Shared helpers for the in-memory BotDetection analysis pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from ua_csv_analysis import AnalysisError as CsvAnalysisError
from ua_csv_analysis import is_null_or_empty, is_unknown, normalize_text, read_csv_with_fallback


INVALID_IP_VALUES = {"", "NULL", "N/A", "NA", "-"}
INVALID_SUBNET_VALUES = {"", "NULL", "N/A", "NA", "-", "."}
INVALID_RECORD_COUNT_VALUES = {"", "NULL", "N/A", "NA", "-", "OTHER", "UNKNOWN"}

CANONICAL_COLUMN_ALIASES = {
    "AdminComment": ["AdminComment"],
    "IPAddress": ["IPAddress", "IpAddress", "LastIpAddress", "LastIPAddress"],
    "CreatedOnUtc": ["CreatedOnUtc"],
    "RangeSubnet24": ["RangeSubnet24", "RangesSubnet24"],
    "RangeSubnet16": ["RangeSubnet16", "RangesSubnet16"],
    "CleanAdminComment": ["CleanAdminComment"],
    "RecordCount": ["RecordCount"],
}

DEFAULT_CANONICAL_COLUMNS = {
    "IPAddress": "",
    "CreatedOnUtc": "",
    "RangeSubnet24": "",
    "RangeSubnet16": "",
    "CleanAdminComment": "",
    "RecordCount": "1",
}


class PipelineError(Exception):
    """Raised when the pipeline cannot prepare input rows."""


@dataclass
class PreparedInput:
    """Normalized input data and audit details shared by all modules."""

    rows: pd.DataFrame
    total_original_rows: int
    skipped_admin_comment_rows: int
    warnings: list[str]


@dataclass
class ModuleStatus:
    """Status for one analysis or scoring module."""

    name: str
    filename: str
    success: bool
    rows_written: int = 0
    error: str = ""


def project_root() -> Path:
    """Return the repository root."""
    return Path(__file__).resolve().parents[1]


def create_output_dir(run_start: datetime) -> Path:
    """Create a timestamped output folder for this run."""
    output_root = project_root() / "Output"
    output_root.mkdir(parents=True, exist_ok=True)

    base_name = run_start.strftime("%Y-%m-%d_%H%M%S")
    output_dir = output_root / base_name
    counter = 1
    while output_dir.exists():
        output_dir = output_root / f"{base_name}_{counter}"
        counter += 1

    output_dir.mkdir(parents=True)
    return output_dir


def normalize_column_key(column_name: Any) -> str:
    """Normalize a CSV column name for case-insensitive matching."""
    return str(column_name).lstrip("\ufeff").strip().casefold()


def canonical_column_name(column_name: Any) -> str:
    """Return the internal column name for one incoming CSV column."""
    cleaned_name = str(column_name).lstrip("\ufeff").strip()
    normalized_name = normalize_column_key(cleaned_name)

    for canonical_name, aliases in CANONICAL_COLUMN_ALIASES.items():
        if normalized_name in {normalize_column_key(alias) for alias in aliases}:
            return canonical_name

    return cleaned_name


def canonicalize_input_columns(df: pd.DataFrame, warnings: list[str]) -> pd.DataFrame:
    """Collapse alias columns so each canonical field appears only once."""
    first_group_order: list[str] = []
    groups: dict[str, list[dict[str, Any]]] = {}

    for position, original_column in enumerate(df.columns):
        source_name = str(original_column).lstrip("\ufeff").strip()
        canonical_name = canonical_column_name(source_name)
        canonical_key = normalize_column_key(canonical_name)
        entry = {
            "position": position,
            "source_name": source_name,
            "canonical": canonical_name,
            "is_exact_canonical": source_name == canonical_name,
        }
        if canonical_key not in groups:
            first_group_order.append(canonical_key)
            groups[canonical_key] = []
        groups[canonical_key].append(entry)

    selected_entries: list[dict[str, Any]] = []
    for canonical_key in first_group_order:
        group = groups[canonical_key]
        preferred = next((entry for entry in group if entry["is_exact_canonical"]), group[0])
        selected_entries.append(preferred)

        for entry in group:
            if entry is preferred:
                continue
            warnings.append(
                "Skipped duplicate CSV column "
                f"{entry['source_name']} because it maps to {preferred['canonical']} "
                f"already provided by {preferred['source_name']}."
            )

    final_df = pd.DataFrame(index=df.index)
    for entry in selected_entries:
        final_df[entry["canonical"]] = df.iloc[:, entry["position"]]

    return final_df


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


def volume_score(record_count: float) -> int:
    """Score candidate traffic volume from 0 to 15."""
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


def load_and_prepare_results(input_path: Path) -> PreparedInput:
    """Read Results.csv once, normalize columns, and prepare reusable fields."""
    try:
        raw_df = read_csv_with_fallback(input_path)
    except CsvAnalysisError as exc:
        raise PipelineError(str(exc)) from exc

    warnings: list[str] = []
    total_original_rows = len(raw_df)
    working = canonicalize_input_columns(raw_df, warnings)

    if "AdminComment" not in working.columns:
        raise PipelineError("Input CSV is missing required column: AdminComment")

    for canonical_name, default_value in DEFAULT_CANONICAL_COLUMNS.items():
        if canonical_name not in working.columns:
            working[canonical_name] = default_value

    working["AdminComment"] = working["AdminComment"].map(normalize_text)
    valid_admin_comment = ~working["AdminComment"].map(is_null_or_empty)
    skipped_admin_comment_rows = int((~valid_admin_comment).sum())
    working = working.loc[valid_admin_comment].copy().reset_index(drop=True)

    raw_counts = working["RecordCount"].map(normalize_text)
    missing_counts = raw_counts.str.upper().isin(INVALID_RECORD_COUNT_VALUES) | raw_counts.map(is_unknown)
    numeric_counts = pd.to_numeric(raw_counts.mask(missing_counts, "0"), errors="coerce")
    invalid_counts = int(numeric_counts.isna().sum())
    if invalid_counts:
        warnings.append(
            f"RecordCount had {invalid_counts} non-numeric value(s); those rows use weight 0."
        )
    working["RecordCount"] = raw_counts
    working["_RecordWeight"] = numeric_counts.fillna(0).astype(float)

    for column in [
        "CleanAdminComment",
        "IPAddress",
        "RangeSubnet24",
        "RangeSubnet16",
        "CreatedOnUtc",
    ]:
        working[column] = working[column].map(normalize_text)

    working["ValidIPAddress"] = working["IPAddress"].map(normalize_ip_address)
    working["ValidSubnet24"] = working["RangeSubnet24"].map(
        lambda value: normalize_invalid_text(value, INVALID_SUBNET_VALUES)
    )
    working["ValidSubnet16"] = working["RangeSubnet16"].map(
        lambda value: normalize_invalid_text(value, INVALID_SUBNET_VALUES)
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


def write_dataframe(df: pd.DataFrame, output_dir: Path, filename: str) -> None:
    """Write a dataframe as UTF-8 CSV."""
    df.to_csv(output_dir / filename, index=False, encoding="utf-8")


def run_module(
    name: str,
    filename: str,
    rows: pd.DataFrame,
    output_dir: Path,
    builder: Callable[[pd.DataFrame], pd.DataFrame],
) -> tuple[pd.DataFrame, ModuleStatus]:
    """Run one analysis module, save its output, and capture failures."""
    try:
        result = builder(rows)
        write_dataframe(result, output_dir, filename)
        status = ModuleStatus(
            name=name,
            filename=filename,
            success=True,
            rows_written=len(result),
        )
        return result, status
    except Exception as exc:
        pd.DataFrame().to_csv(output_dir / filename, index=False, encoding="utf-8")
        status = ModuleStatus(
            name=name,
            filename=filename,
            success=False,
            error=str(exc),
        )
        return pd.DataFrame(), status


def write_run_summary(
    output_dir: Path,
    input_path: Path,
    run_start: datetime,
    run_end: datetime,
    prepared_input: PreparedInput | None,
    statuses: list[ModuleStatus],
    scoring_result: Any,
) -> None:
    """Write the final run summary."""
    lines = [
        "BotDetection Analysis Pipeline Run Summary",
        "",
        f"Input file path: {input_path}",
        f"Output folder: {output_dir}",
        f"Run start time: {run_start.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Run end time: {run_end.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Total original rows: {prepared_input.total_original_rows if prepared_input else 0}",
        (
            "Total prepared rows: "
            f"{len(prepared_input.rows) if prepared_input is not None else 0}"
        ),
        (
            "Skipped rows: "
            f"{prepared_input.skipped_admin_comment_rows if prepared_input else 0} "
            "row(s) with null/empty/literal NULL AdminComment"
        ),
        "",
        "Analysis modules:",
    ]

    for status in statuses:
        state = "SUCCESS" if status.success else "FAILED"
        detail = f"{status.rows_written} row(s) written" if status.success else status.error
        lines.append(f"- {status.name} ({status.filename}): {state} - {detail}")

    lines.append("")
    lines.append("Scoring:")
    if scoring_result is None:
        lines.append("- NOT RUN")
    else:
        state = "SUCCESS" if scoring_result.success else "FAILED"
        lines.append(f"- build_scoring_reports.py: {state}")
        for filename, row_count in scoring_result.rows_written.items():
            lines.append(f"  - {filename}: {row_count} row(s) written")

        if scoring_result.warnings:
            lines.append("")
            lines.append("Scoring warnings:")
            lines.extend([f"- {warning}" for warning in scoring_result.warnings])

        if scoring_result.errors:
            lines.append("")
            lines.append("Scoring errors:")
            lines.extend([f"- {error}" for error in scoring_result.errors])

    if prepared_input and prepared_input.warnings:
        lines.append("")
        lines.append("Input warnings:")
        lines.extend([f"- {warning}" for warning in prepared_input.warnings])

    (output_dir / "Run_Summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
