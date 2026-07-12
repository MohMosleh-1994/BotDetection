"""Parse User-Agent CSV exports and write structured analysis files."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd
from pandas.errors import ParserError
from ua_parser import user_agent_parser


SUPPORTED_ENCODINGS = ("utf-8", "utf-8-sig", "windows-1252")
UNKNOWN_VALUES = {"", "NULL", "OTHER", "UNKNOWN"}

PARSED_OUTPUT_COLUMNS = [
    "CleanAdminComment",
    "AdminComment",
    "RecordCount",
    "BrowserFamily",
    "BrowserMajor",
    "BrowserMinor",
    "BrowserPatch",
    "BrowserVersion",
    "OSFamily",
    "OSMajor",
    "OSMinor",
    "OSPatch",
    "OSVersion",
    "DeviceFamily",
    "DeviceBrand",
    "DeviceModel",
    "IsBrowserKnown",
    "IsOSKnown",
    "IsDeviceKnown",
    "MissingFieldCount",
    "StructureDecision",
]

SUMMARY_OUTPUT_COLUMNS = [
    "CleanAdminComment",
    "BrowserFamily",
    "OSFamily",
    "DeviceFamily",
    "TotalRecords",
    "UniqueUserAgents",
    "ParsedRecordCount",
    "BrowserFamilyCoveragePercent",
]


class AnalysisError(Exception):
    """Raised when the CSV analysis cannot continue safely."""


def normalize_text(value: Any) -> str:
    """Return a stripped string value, using an empty string for null-like input."""
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def is_null_or_empty(value: Any) -> bool:
    """Check whether input data is missing or a literal NULL value."""
    return normalize_text(value).upper() in {"", "NULL"}


def is_unknown(value: Any) -> bool:
    """Check whether a parsed value should be treated as unknown."""
    return normalize_text(value).upper() in UNKNOWN_VALUES


def normalize_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """Strip whitespace and a possible UTF-8 BOM from CSV column names."""
    df.columns = [str(column).lstrip("\ufeff").strip() for column in df.columns]
    return df


def read_csv_with_fallback(input_path: Path) -> pd.DataFrame:
    """Read a CSV file by trying the supported encodings in order."""
    if not input_path.exists():
        raise AnalysisError(f"Input file does not exist: {input_path}")

    if not input_path.is_file():
        raise AnalysisError(f"Input path is not a file: {input_path}")

    last_error: Exception | None = None

    for encoding in SUPPORTED_ENCODINGS:
        try:
            df = pd.read_csv(
                input_path,
                dtype=str,
                keep_default_na=False,
                encoding=encoding,
            )
            return normalize_column_names(df)
        except UnicodeDecodeError as exc:
            last_error = exc
        except ParserError as exc:
            raise AnalysisError(f"Invalid CSV format: {exc}") from exc
        except OSError as exc:
            raise AnalysisError(f"Could not read input file: {exc}") from exc

    raise AnalysisError(
        "Unable to read CSV using supported encodings: "
        f"{', '.join(SUPPORTED_ENCODINGS)}. Last error: {last_error}"
    )


def validate_input_columns(df: pd.DataFrame) -> None:
    """Validate required input columns."""
    if "AdminComment" not in df.columns:
        raise AnalysisError("Input CSV must contain the required AdminComment column.")


def version_string(parts: list[Any]) -> str:
    """Join known version parts with dots while skipping null/empty parts."""
    known_parts = [normalize_text(part) for part in parts if not is_unknown(part)]
    return ".".join(known_parts)


def prepare_input_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize optional columns, skip empty User-Agents, and prepare record weights."""
    working = df.copy()

    if "CleanAdminComment" not in working.columns:
        working["CleanAdminComment"] = ""

    if "RecordCount" not in working.columns:
        working["RecordCount"] = "1"
        working["_RecordWeight"] = 1.0
    else:
        raw_counts = working["RecordCount"].map(normalize_text)
        missing_counts = raw_counts.map(is_unknown)
        numeric_counts = pd.to_numeric(raw_counts.mask(missing_counts, "0"), errors="coerce")

        invalid_counts = numeric_counts.isna()
        if invalid_counts.any():
            row_numbers = [str(index + 2) for index in invalid_counts[invalid_counts].index[:10]]
            raise AnalysisError(
                "RecordCount contains non-numeric values near CSV row(s): "
                + ", ".join(row_numbers)
            )

        working["RecordCount"] = raw_counts
        working["_RecordWeight"] = numeric_counts.astype(float)

    working["CleanAdminComment"] = working["CleanAdminComment"].map(normalize_text)
    working["AdminComment"] = working["AdminComment"].map(normalize_text)

    valid_user_agents = ~working["AdminComment"].map(is_null_or_empty)
    return working.loc[valid_user_agents].reset_index(drop=True)


def parse_user_agent(admin_comment: str) -> dict[str, Any]:
    """Parse one User-Agent and return normalized parser fields."""
    parsed = user_agent_parser.Parse(admin_comment)
    browser = parsed.get("user_agent", {}) or {}
    os_info = parsed.get("os", {}) or {}
    device = parsed.get("device", {}) or {}

    browser_family = normalize_text(browser.get("family"))
    browser_major = normalize_text(browser.get("major"))
    browser_minor = normalize_text(browser.get("minor"))
    browser_patch = normalize_text(browser.get("patch"))
    browser_version = version_string([browser_major, browser_minor, browser_patch])

    os_family = normalize_text(os_info.get("family"))
    os_major = normalize_text(os_info.get("major"))
    os_minor = normalize_text(os_info.get("minor"))
    os_patch = normalize_text(os_info.get("patch"))
    os_version = version_string([os_major, os_minor, os_patch])

    device_family = normalize_text(device.get("family"))
    device_brand = normalize_text(device.get("brand"))
    device_model = normalize_text(device.get("model"))

    is_browser_known = not is_unknown(browser_family)
    is_os_known = not is_unknown(os_family)
    is_device_known = not is_unknown(device_family)

    missing_field_count = sum(
        [
            not is_browser_known,
            is_unknown(browser_version),
            not is_os_known,
        ]
    )

    if missing_field_count == 0:
        structure_decision = "COMPLETE"
    elif missing_field_count == 1:
        structure_decision = "PARTIAL"
    else:
        structure_decision = "WORTH CHECKING"

    return {
        "BrowserFamily": browser_family,
        "BrowserMajor": browser_major,
        "BrowserMinor": browser_minor,
        "BrowserPatch": browser_patch,
        "BrowserVersion": browser_version,
        "OSFamily": os_family,
        "OSMajor": os_major,
        "OSMinor": os_minor,
        "OSPatch": os_patch,
        "OSVersion": os_version,
        "DeviceFamily": device_family,
        "DeviceBrand": device_brand,
        "DeviceModel": device_model,
        "IsBrowserKnown": is_browser_known,
        "IsOSKnown": is_os_known,
        "IsDeviceKnown": is_device_known,
        "MissingFieldCount": missing_field_count,
        "StructureDecision": structure_decision,
    }


def build_parsed_rows(input_rows: pd.DataFrame) -> pd.DataFrame:
    """Build the row-level parsed output data."""
    parsed_rows: list[dict[str, Any]] = []

    for _, row in input_rows.iterrows():
        parsed_fields = parse_user_agent(row["AdminComment"])
        parsed_rows.append(
            {
                "CleanAdminComment": row["CleanAdminComment"],
                "AdminComment": row["AdminComment"],
                "RecordCount": row["RecordCount"],
                "_RecordWeight": row["_RecordWeight"],
                **parsed_fields,
            }
        )

    if not parsed_rows:
        return pd.DataFrame(columns=[*PARSED_OUTPUT_COLUMNS, "_RecordWeight"])

    return pd.DataFrame(parsed_rows)


def build_summary(parsed_df: pd.DataFrame) -> pd.DataFrame:
    """Build the grouped family summary output."""
    if parsed_df.empty:
        return pd.DataFrame(columns=SUMMARY_OUTPUT_COLUMNS)

    group_columns = ["CleanAdminComment", "BrowserFamily", "OSFamily", "DeviceFamily"]

    summary = (
        parsed_df.groupby(group_columns, dropna=False)
        .agg(
            TotalRecords=("_RecordWeight", "sum"),
            UniqueUserAgents=("AdminComment", "nunique"),
            ParsedRecordCount=("AdminComment", "size"),
        )
        .reset_index()
    )

    browser_totals = (
        parsed_df.groupby(["CleanAdminComment", "BrowserFamily"], dropna=False)["_RecordWeight"]
        .sum()
        .reset_index(name="BrowserFamilyRecords")
    )
    clean_totals = (
        parsed_df.groupby("CleanAdminComment", dropna=False)["_RecordWeight"]
        .sum()
        .reset_index(name="CleanAdminCommentRecords")
    )
    coverage = browser_totals.merge(clean_totals, on="CleanAdminComment", how="left")
    clean_total_denominator = coverage["CleanAdminCommentRecords"].where(
        coverage["CleanAdminCommentRecords"] != 0
    )
    coverage["BrowserFamilyCoveragePercent"] = (
        coverage["BrowserFamilyRecords"] * 100.0 / clean_total_denominator
    ).round(2)

    summary = summary.merge(
        coverage[["CleanAdminComment", "BrowserFamily", "BrowserFamilyCoveragePercent"]],
        on=["CleanAdminComment", "BrowserFamily"],
        how="left",
    )

    summary["TotalRecords"] = summary["TotalRecords"].round(0).astype("int64")
    return summary[SUMMARY_OUTPUT_COLUMNS].sort_values(
        by=["CleanAdminComment", "TotalRecords", "BrowserFamilyCoveragePercent"],
        ascending=[True, False, False],
    )


def write_outputs(parsed_df: pd.DataFrame, summary_df: pd.DataFrame, input_path: Path) -> tuple[Path, Path]:
    """Write parsed and summary CSV files into the project Output folder."""
    project_root = Path(__file__).resolve().parents[1]
    output_dir = project_root / "Output"
    output_dir.mkdir(parents=True, exist_ok=True)

    parsed_output = output_dir / f"{input_path.stem}_parsed.csv"
    summary_output = output_dir / "user_agent_family_summary.csv"

    parsed_df[PARSED_OUTPUT_COLUMNS].to_csv(parsed_output, index=False, encoding="utf-8")
    summary_df.to_csv(summary_output, index=False, encoding="utf-8")

    return parsed_output, summary_output


def analyze_csv(input_path: Path) -> tuple[Path, Path, int]:
    """Run the full CSV analysis and return output paths plus parsed row count."""
    df = read_csv_with_fallback(input_path)
    validate_input_columns(df)
    input_rows = prepare_input_rows(df)
    parsed_df = build_parsed_rows(input_rows)
    summary_df = build_summary(parsed_df)
    parsed_output, summary_output = write_outputs(parsed_df, summary_df, input_path)
    return parsed_output, summary_output, len(parsed_df)


def main(argv: list[str]) -> int:
    """CLI entry point."""
    if len(argv) != 2:
        print("Usage: python Python/ua_csv_analysis.py <input_csv_path>", file=sys.stderr)
        return 2

    input_path = Path(argv[1])

    try:
        parsed_output, summary_output, parsed_count = analyze_csv(input_path)
    except AnalysisError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Parsed rows: {parsed_count}")
    print(f"Parsed output: {parsed_output}")
    print(f"Summary output: {summary_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
