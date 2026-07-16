"""Main BotDetection in-memory analysis pipeline entry point."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import candidate_ranking
import global_ip_analysis
import global_subnet16_analysis
import global_subnet24_analysis
import ip_analysis
import subnet24_analysis
import time_analysis
from build_scoring_reports import build_reports
from pipeline_common import (
    ModuleStatus,
    create_output_dir,
    load_and_prepare_results,
    run_module,
    write_run_summary,
)
from ua_structure_runner import run_user_agent_parser


ANALYSIS_MODULES = [
    (
        "User-Agent Candidate Ranking",
        "Candidate_Summary.csv",
        candidate_ranking.analyze,
    ),
    ("Time Analysis", "Time_Analysis.csv", time_analysis.analyze),
    ("Per-UA IP Analysis", "PerUA_IP_Analysis.csv", ip_analysis.analyze),
    (
        "Per-UA /24 Analysis",
        "PerUA_Subnet24_Analysis.csv",
        subnet24_analysis.analyze,
    ),
    ("Global IP Analysis", "Global_IP_Analysis.csv", global_ip_analysis.analyze),
    (
        "Global /24 Analysis",
        "Global_Subnet24_Analysis.csv",
        global_subnet24_analysis.analyze,
    ),
    (
        "Global /16 Analysis",
        "Global_Subnet16_Analysis.csv",
        global_subnet16_analysis.analyze,
    ),
]


def run_pipeline(input_path: Path) -> tuple[Path, bool]:
    """Run pandas analyses, User-Agent parsing, then final scoring reports."""
    run_start = datetime.now()
    output_dir = create_output_dir(run_start)
    statuses: list[ModuleStatus] = []
    prepared_input = None
    scoring_result = None

    try:
        prepared_input = load_and_prepare_results(input_path)
    except Exception as exc:
        statuses.append(
            ModuleStatus(
                name="Input Preparation",
                filename=str(input_path),
                success=False,
                error=str(exc),
            )
        )
        write_run_summary(
            output_dir=output_dir,
            input_path=input_path,
            run_start=run_start,
            run_end=datetime.now(),
            prepared_input=prepared_input,
            statuses=statuses,
            scoring_result=scoring_result,
        )
        return output_dir, False

    rows = prepared_input.rows

    for name, filename, builder in ANALYSIS_MODULES:
        _, status = run_module(name, filename, rows, output_dir, builder)
        statuses.append(status)

    statuses.append(run_user_agent_parser(rows, output_dir))
    scoring_result = build_reports(output_dir)

    write_run_summary(
        output_dir=output_dir,
        input_path=input_path,
        run_start=run_start,
        run_end=datetime.now(),
        prepared_input=prepared_input,
        statuses=statuses,
        scoring_result=scoring_result,
    )

    analysis_success = all(status.success for status in statuses)
    return output_dir, analysis_success and scoring_result.success


def main(argv: list[str]) -> int:
    """CLI entry point."""
    if len(argv) != 2:
        print('Usage: python Python/run_analysis_pipeline.py "<Results.csv path>"', file=sys.stderr)
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
