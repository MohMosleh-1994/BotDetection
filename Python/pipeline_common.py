"""Shared helpers for BotDetection pipeline entry points."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


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


def write_run_summary(
    output_dir: Path,
    input_path: Path,
    run_start: datetime,
    run_end: datetime,
    original_row_count: int,
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
        f"Total original rows: {original_row_count}",
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

    (output_dir / "Run_Summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
