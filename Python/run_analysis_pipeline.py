"""Main BotDetection pipeline entry point."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from build_scoring_reports import build_reports
from pipeline_common import create_output_dir, write_run_summary
from sql_analysis_runner import run_sql_analysis_modules
from ua_structure_runner import run_user_agent_parser


def run_pipeline(input_path: Path) -> tuple[Path, bool]:
    """Run SQL analyses, User-Agent parsing, then final scoring reports."""
    run_start = datetime.now()
    output_dir = create_output_dir(run_start)

    statuses, original_row_count = run_sql_analysis_modules(input_path, output_dir)
    statuses.append(run_user_agent_parser(input_path, output_dir))

    scoring_result = build_reports(output_dir)

    write_run_summary(
        output_dir=output_dir,
        input_path=input_path,
        run_start=run_start,
        run_end=datetime.now(),
        original_row_count=original_row_count,
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
