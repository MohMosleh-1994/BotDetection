"""Execute approved SQL analysis files against a local Results CSV."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd

from pipeline_common import ModuleStatus, project_root
from ua_csv_analysis import AnalysisError as CsvAnalysisError
from ua_csv_analysis import read_csv_with_fallback


SQL_MODULES = [
    ("User-Agent Candidate Ranking", "SQL/00_UserAgent_Candidate_Ranking.sql", "Candidate_Summary.csv"),
    ("Time Analysis", "Time Analysis.sql", "Time_Analysis.csv"),
    ("Per-UA IP Analysis", "03_Network_Analysis_IP.sql", "PerUA_IP_Analysis.csv"),
    ("Per-UA /24 Analysis", "03_Network_Analysis_Subnet24.sql", "PerUA_Subnet24_Analysis.csv"),
    ("Global IP Analysis", "04_Global_IP_Analysis.sql", "Global_IP_Analysis.csv"),
    ("Global /24 Analysis", "05_Global_Subnet24_Analysis.sql", "Global_Subnet24_Analysis.csv"),
    ("Global /16 Analysis", "06_Global_Subnet16_Analysis.sql", "Global_Subnet16_Analysis.csv"),
]


def normalize_column_key(column_name: Any) -> str:
    """Normalize a CSV column name for case-insensitive matching."""
    return str(column_name).lstrip("\ufeff").strip().casefold()


def find_column(df: pd.DataFrame, aliases: list[str]) -> str | None:
    """Find a column using case-insensitive aliases."""
    columns_by_key = {normalize_column_key(column): column for column in df.columns}
    for alias in aliases:
        column = columns_by_key.get(normalize_column_key(alias))
        if column is not None:
            return column
    return None


def ensure_column(
    df: pd.DataFrame,
    canonical_name: str,
    aliases: list[str],
    *,
    required: bool = False,
    default_value: str = "",
) -> None:
    """Create a canonical column expected by the SQL scripts."""
    source_column = find_column(df, aliases)
    if source_column is None:
        if required:
            raise ValueError(f"Input CSV is missing required column: {canonical_name}")
        df[canonical_name] = default_value
        return

    if source_column != canonical_name:
        df[canonical_name] = df[source_column]


def load_results_dataframe(input_path: Path) -> pd.DataFrame:
    """Load the original Results CSV and add SQL-friendly column aliases."""
    try:
        df = read_csv_with_fallback(input_path)
    except CsvAnalysisError as exc:
        raise ValueError(str(exc)) from exc

    df = df.copy()
    ensure_column(df, "AdminComment", ["AdminComment"], required=True)
    ensure_column(df, "IPAddress", ["IPAddress", "IpAddress", "LastIpAddress"], default_value="")
    ensure_column(df, "CreatedOnUtc", ["CreatedOnUtc"], default_value="")
    ensure_column(df, "RangeSubnet24", ["RangeSubnet24", "RangesSubnet24"], default_value="")
    ensure_column(df, "RangeSubnet16", ["RangeSubnet16", "RangesSubnet16"], default_value="")
    ensure_column(df, "CleanAdminComment", ["CleanAdminComment"], default_value="")
    ensure_column(df, "RecordCount", ["RecordCount"], default_value="1")
    return df


def translate_tsql_for_duckdb(sql_text: str) -> str:
    """Adapt the approved SQL Server scripts for local DuckDB execution."""
    sql = sql_text.lstrip("\ufeff")

    sql = re.sub(r"DECLARE\s+@\w+\s+\w+\s*=\s*([^;]+);", "", sql, flags=re.IGNORECASE)
    sql = sql.replace("@WindowMinutes", "5")

    sql = re.sub(
        r"DATEADD\s*\(\s*MINUTE\s*,\s*DATEDIFF\s*\(\s*MINUTE\s*,\s*0\s*,\s*([A-Za-z0-9_.]+)\s*\)\s*,\s*0\s*\)",
        r"DATE_TRUNC('minute', \1)",
        sql,
        flags=re.IGNORECASE,
    )
    sql = re.sub(
        r"DATEADD\s*\(\s*MINUTE\s*,\s*-\s*5\s*,\s*([A-Za-z0-9_.]+)\s*\)",
        r"(\1 - INTERVAL 5 MINUTE)",
        sql,
        flags=re.IGNORECASE,
    )
    sql = re.sub(
        r"DATEADD\s*\(\s*MINUTE\s*,\s*\+?\s*5\s*,\s*([A-Za-z0-9_.]+)\s*\)",
        r"(\1 + INTERVAL 5 MINUTE)",
        sql,
        flags=re.IGNORECASE,
    )
    sql = re.sub(
        r"DATEDIFF\s*\(\s*MINUTE\s*,\s*([^,]+?)\s*,\s*([^)]+?)\s*\)",
        r"DATE_DIFF('minute', \1, \2)",
        sql,
        flags=re.IGNORECASE,
    )
    sql = re.sub(
        r"TRY_CONVERT\s*\(\s*datetime2\s*,\s*([^)]+?)\s*\)",
        r"TRY_CAST(\1 AS TIMESTAMP)",
        sql,
        flags=re.IGNORECASE,
    )
    sql = re.sub(
        r"CHARINDEX\s*\(\s*','\s*,\s*([A-Za-z0-9_.]+)\s*\)",
        r"STRPOS(\1, ',')",
        sql,
        flags=re.IGNORECASE,
    )
    percentile_pattern = (
        r"PERCENTILE_CONT\s*\(\s*0\.5\s*\)\s*WITHIN\s+GROUP\s*"
        r"\(\s*ORDER\s+BY\s+([A-Za-z0-9_.]+)\s*\)\s*OVER\s*"
        r"\(\s*PARTITION\s+BY\s+([^)]+?)\s*\)"
    )
    sql = re.sub(
        percentile_pattern,
        r"MEDIAN(\1) OVER (PARTITION BY \2)",
        sql,
        flags=re.IGNORECASE,
    )

    return sql


def write_empty_outputs(output_dir: Path, statuses: list[ModuleStatus], error: str) -> None:
    """Write empty CSVs for SQL modules that could not run."""
    for name, _, filename in SQL_MODULES:
        pd.DataFrame().to_csv(output_dir / filename, index=False, encoding="utf-8")
        statuses.append(ModuleStatus(name=name, filename=filename, success=False, error=error))


def run_sql_analysis_modules(input_path: Path, output_dir: Path) -> tuple[list[ModuleStatus], int]:
    """Load Results.csv, execute approved SQL files, and save CSV outputs."""
    statuses: list[ModuleStatus] = []

    try:
        results_df = load_results_dataframe(input_path)
    except Exception as exc:
        write_empty_outputs(output_dir, statuses, str(exc))
        return statuses, 0

    try:
        import duckdb
    except ImportError:
        write_empty_outputs(
            output_dir,
            statuses,
            "Missing dependency: duckdb. Install requirements.txt.",
        )
        return statuses, len(results_df)

    connection = duckdb.connect(database=":memory:")
    connection.register("Results", results_df)

    for name, relative_sql_path, output_filename in SQL_MODULES:
        sql_path = project_root() / relative_sql_path
        output_path = output_dir / output_filename

        try:
            sql_text = sql_path.read_text(encoding="utf-8")
            translated_sql = translate_tsql_for_duckdb(sql_text)
            result_df = connection.execute(translated_sql).df()
            result_df.to_csv(output_path, index=False, encoding="utf-8")
            statuses.append(
                ModuleStatus(
                    name=name,
                    filename=output_filename,
                    success=True,
                    rows_written=len(result_df),
                )
            )
        except Exception as exc:
            pd.DataFrame().to_csv(output_path, index=False, encoding="utf-8")
            statuses.append(
                ModuleStatus(
                    name=name,
                    filename=output_filename,
                    success=False,
                    error=str(exc),
                )
            )

    connection.close()
    return statuses, len(results_df)
