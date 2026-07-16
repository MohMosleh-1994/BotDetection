"""Run the User-Agent parser module and save pipeline-ready outputs."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from pipeline_common import ModuleStatus
from ua_csv_analysis import (
    build_parsed_rows,
    build_summary,
    is_unknown,
    prepare_input_rows,
    read_csv_with_fallback,
    validate_input_columns,
)


UA_SCORE_BY_DECISION = {
    "WORTH CHECKING": 10,
    "PARTIAL": 5,
    "COMPLETE": 0,
}


def build_ua_reason(row: pd.Series) -> str:
    """Explain which structural User-Agent fields are missing."""
    missing_fields: list[str] = []
    if is_unknown(row.get("BrowserFamily")):
        missing_fields.append("BrowserFamily")
    if is_unknown(row.get("BrowserVersion")):
        missing_fields.append("BrowserVersion")
    if is_unknown(row.get("OSFamily")):
        missing_fields.append("OSFamily")

    if not missing_fields:
        return "Browser family, browser version, and OS family are available."
    return "Missing: " + ", ".join(missing_fields)


def run_user_agent_parser(input_path: Path, output_dir: Path) -> ModuleStatus:
    """Call ua_csv_analysis.py logic and write UA analysis outputs."""
    output_filename = "UA_Structure_Analysis.csv"

    try:
        results_df = read_csv_with_fallback(input_path)
        validate_input_columns(results_df)
        input_rows = prepare_input_rows(results_df)
        parsed_df = build_parsed_rows(input_rows)
        summary_df = build_summary(parsed_df)

        ua_structure = pd.DataFrame(
            {
                "AdminComment": parsed_df["AdminComment"],
                "BrowserFamily": parsed_df["BrowserFamily"],
                "BrowserVersion": parsed_df["BrowserVersion"],
                "OSFamily": parsed_df["OSFamily"],
                "OSVersion": parsed_df["OSVersion"],
                "DeviceFamily": parsed_df["DeviceFamily"],
                "UAStructureDecision": parsed_df["StructureDecision"],
            }
        )
        ua_structure["UAReason"] = ua_structure.apply(build_ua_reason, axis=1)
        ua_structure["UAStructureScore"] = (
            ua_structure["UAStructureDecision"].map(UA_SCORE_BY_DECISION).fillna(0).astype(int)
        )

        ua_structure.to_csv(output_dir / output_filename, index=False, encoding="utf-8")
        parsed_df.drop(columns=["_RecordWeight"], errors="ignore").to_csv(
            output_dir / "ua_csv_analysis_parsed.csv",
            index=False,
            encoding="utf-8",
        )
        summary_df.to_csv(output_dir / "user_agent_family_summary.csv", index=False, encoding="utf-8")

        return ModuleStatus(
            name="User-Agent Structure Analysis",
            filename=output_filename,
            success=True,
            rows_written=len(ua_structure),
        )
    except Exception as exc:
        pd.DataFrame().to_csv(output_dir / output_filename, index=False, encoding="utf-8")
        return ModuleStatus(
            name="User-Agent Structure Analysis",
            filename=output_filename,
            success=False,
            error=str(exc),
        )
