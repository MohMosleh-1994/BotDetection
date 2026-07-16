"""Execute approved SQL Server analysis files against an imported Results CSV."""

from __future__ import annotations

import os
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

RESULTS_TABLE = "dbo.Results"
PIPELINE_MARKER = "BotDetectionPipelineTable"
INSERT_BATCH_SIZE = 1000


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


def sql_bool_env(name: str, default: bool = False) -> bool:
    """Read a boolean environment variable."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "y", "on"}


def build_connection_string() -> str:
    """Build a SQL Server pyodbc connection string from environment settings."""
    override = os.getenv("BOTDETECTION_SQL_CONNECTION_STRING")
    if override:
        return override

    driver = os.getenv("BOTDETECTION_SQL_DRIVER", "ODBC Driver 17 for SQL Server")
    server = os.getenv("BOTDETECTION_SQL_SERVER", "localhost")
    database = os.getenv("BOTDETECTION_SQL_DATABASE", "tempdb")
    username = os.getenv("BOTDETECTION_SQL_USERNAME", "")
    password = os.getenv("BOTDETECTION_SQL_PASSWORD", "")
    trust_certificate = os.getenv("BOTDETECTION_SQL_TRUST_SERVER_CERTIFICATE", "yes")

    parts = [
        f"DRIVER={{{driver}}}",
        f"SERVER={server}",
        f"DATABASE={database}",
        f"TrustServerCertificate={trust_certificate}",
    ]

    if username or password:
        parts.extend([f"UID={username}", f"PWD={password}"])
    else:
        parts.append("Trusted_Connection=yes")

    return ";".join(parts) + ";"


def quote_identifier(identifier: str) -> str:
    """Quote a SQL Server identifier."""
    return "[" + str(identifier).replace("]", "]]") + "]"


def is_pipeline_results_table(cursor: Any) -> bool:
    """Return whether dbo.Results was created by this pipeline."""
    cursor.execute(
        """
        SELECT CAST(ep.value AS nvarchar(100))
        FROM sys.extended_properties ep
        WHERE ep.major_id = OBJECT_ID(N'dbo.Results')
          AND ep.minor_id = 0
          AND ep.name = ?
        """,
        PIPELINE_MARKER,
    )
    row = cursor.fetchone()
    return bool(row and str(row[0]) == "1")


def drop_results_table(cursor: Any, *, allow_existing_table: bool = False) -> None:
    """Drop dbo.Results only when safe to do so."""
    cursor.execute("SELECT OBJECT_ID(N'dbo.Results', N'U')")
    row = cursor.fetchone()
    if not row or row[0] is None:
        return

    if not allow_existing_table and not is_pipeline_results_table(cursor):
        raise RuntimeError(
            "dbo.Results already exists and is not marked as a BotDetection "
            "pipeline table. Set BOTDETECTION_SQL_ALLOW_OVERWRITE_RESULTS=1 "
            "only if this is a scratch/local database."
        )

    cursor.execute("DROP TABLE dbo.Results")


def add_results_table_marker(cursor: Any) -> None:
    """Mark dbo.Results as owned by the BotDetection pipeline."""
    cursor.execute(
        """
        EXEC sys.sp_addextendedproperty
            @name = ?,
            @value = N'1',
            @level0type = N'SCHEMA',
            @level0name = N'dbo',
            @level1type = N'TABLE',
            @level1name = N'Results'
        """,
        PIPELINE_MARKER,
    )


def create_results_table(cursor: Any, df: pd.DataFrame) -> None:
    """Create dbo.Results with text columns matching the CSV headers."""
    columns_sql = ",\n        ".join(
        f"{quote_identifier(column)} nvarchar(max) NULL" for column in df.columns
    )
    cursor.execute(f"CREATE TABLE {RESULTS_TABLE} (\n        {columns_sql}\n    )")
    add_results_table_marker(cursor)


def insert_results_rows(cursor: Any, df: pd.DataFrame) -> None:
    """Insert Results.csv rows into SQL Server in batches."""
    if df.empty:
        return

    import_df = df.where(pd.notna(df), None)
    columns_sql = ", ".join(quote_identifier(column) for column in import_df.columns)
    placeholders = ", ".join("?" for _ in import_df.columns)
    insert_sql = f"INSERT INTO {RESULTS_TABLE} ({columns_sql}) VALUES ({placeholders})"

    cursor.fast_executemany = True
    for start in range(0, len(import_df), INSERT_BATCH_SIZE):
        batch = import_df.iloc[start : start + INSERT_BATCH_SIZE]
        cursor.executemany(insert_sql, list(batch.itertuples(index=False, name=None)))


def import_results_csv(cursor: Any, results_df: pd.DataFrame) -> None:
    """Replace dbo.Results with the current Results.csv contents."""
    allow_existing_table = sql_bool_env("BOTDETECTION_SQL_ALLOW_OVERWRITE_RESULTS")
    drop_results_table(cursor, allow_existing_table=allow_existing_table)
    create_results_table(cursor, results_df)
    insert_results_rows(cursor, results_df)


def dataframe_from_cursor(cursor: Any) -> pd.DataFrame:
    """Read the first result set returned by a SQL Server batch."""
    while cursor.description is None:
        if not cursor.nextset():
            return pd.DataFrame()

    columns = [column[0] for column in cursor.description]
    rows = cursor.fetchall()
    return pd.DataFrame.from_records([tuple(row) for row in rows], columns=columns)


def write_empty_outputs(output_dir: Path, statuses: list[ModuleStatus], error: str) -> None:
    """Write empty CSVs for SQL modules that could not run."""
    for name, _, filename in SQL_MODULES:
        pd.DataFrame().to_csv(output_dir / filename, index=False, encoding="utf-8")
        statuses.append(ModuleStatus(name=name, filename=filename, success=False, error=error))


def execute_sql_file(cursor: Any, sql_path: Path) -> pd.DataFrame:
    """Execute a repository SQL Server script without modifying its text."""
    sql_text = sql_path.read_text(encoding="utf-8-sig")
    cursor.execute(sql_text)
    return dataframe_from_cursor(cursor)


def cleanup_results_table(cursor: Any) -> None:
    """Drop dbo.Results unless the user asks to keep it for debugging."""
    if sql_bool_env("BOTDETECTION_SQL_KEEP_RESULTS"):
        return
    drop_results_table(cursor, allow_existing_table=False)


def run_sql_analysis_modules(input_path: Path, output_dir: Path) -> tuple[list[ModuleStatus], int]:
    """Import Results.csv into SQL Server, run SQL scripts, and save CSV outputs."""
    statuses: list[ModuleStatus] = []

    try:
        results_df = load_results_dataframe(input_path)
    except Exception as exc:
        write_empty_outputs(output_dir, statuses, str(exc))
        return statuses, 0

    try:
        import pyodbc
    except ImportError:
        write_empty_outputs(
            output_dir,
            statuses,
            "Missing dependency: pyodbc. Install requirements.txt.",
        )
        return statuses, len(results_df)

    connection = None
    try:
        connection = pyodbc.connect(build_connection_string())
        cursor = connection.cursor()
        import_results_csv(cursor, results_df)
        connection.commit()

        for name, relative_sql_path, output_filename in SQL_MODULES:
            sql_path = project_root() / relative_sql_path
            output_path = output_dir / output_filename

            try:
                result_df = execute_sql_file(cursor, sql_path)
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

        cleanup_results_table(cursor)
        connection.commit()
    except Exception as exc:
        write_empty_outputs(output_dir, statuses, str(exc))
    finally:
        if connection is not None:
            connection.close()

    return statuses, len(results_df)
