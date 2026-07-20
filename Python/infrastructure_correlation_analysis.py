"""Build infrastructure correlation reports across User-Agents.

This module is independent from the active scoring pipeline. It does not assign
priority, suspicion, or final decision labels. It only exposes shared
infrastructure patterns for analyst review.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from pipeline_common import (
    INVALID_SUBNET_VALUES,
    create_output_dir,
    load_and_prepare_results,
    normalize_count_columns,
    normalize_invalid_text,
    normalize_ip_address,
    write_dataframe,
)


SHARED_IP_INFRASTRUCTURE_FILENAME = "Shared_IP_Infrastructure.csv"
SHARED_SUBNET24_INFRASTRUCTURE_FILENAME = "Shared_Subnet24_Infrastructure.csv"

SHARED_IP_INFRASTRUCTURE_COLUMNS = [
    "IPAddress",
    "TotalRecords",
    "UniqueUserAgents",
    "PeakMinuteUtc",
    "PeakMinuteRecords",
    "MaxConcurrentUserAgents",
]

SHARED_SUBNET24_INFRASTRUCTURE_COLUMNS = [
    "RangeSubnet24",
    "TotalRecords",
    "UniqueIPs",
    "UniqueUserAgents",
    "PeakMinuteUtc",
    "PeakMinuteRecords",
    "MaxConcurrentUserAgents",
]


def _record_weights(rows: pd.DataFrame) -> pd.Series:
    """Return the record weights used by the active in-memory pipeline."""
    if "_RecordWeight" not in rows.columns:
        return pd.Series(1, index=rows.index, dtype="float64")
    return pd.to_numeric(rows["_RecordWeight"], errors="coerce").fillna(0)


def _valid_ip_addresses(rows: pd.DataFrame) -> pd.Series:
    """Return normalized first IP values using the shared pipeline helper."""
    if "ValidIPAddress" in rows.columns:
        return rows["ValidIPAddress"]
    if "IPAddress" in rows.columns:
        return rows["IPAddress"].map(normalize_ip_address)
    return pd.Series(pd.NA, index=rows.index)


def _valid_subnet24_values(rows: pd.DataFrame) -> pd.Series:
    """Return normalized /24 subnet values using the shared pipeline helper."""
    if "ValidSubnet24" in rows.columns:
        return rows["ValidSubnet24"]
    if "RangeSubnet24" in rows.columns:
        return rows["RangeSubnet24"].map(
            lambda value: normalize_invalid_text(value, INVALID_SUBNET_VALUES)
        )
    return pd.Series(pd.NA, index=rows.index)


def _created_on_dates(rows: pd.DataFrame) -> pd.Series:
    """Return parsed CreatedOnUtc values when available."""
    if "CreatedOnUtcDate" in rows.columns:
        return pd.to_datetime(rows["CreatedOnUtcDate"], errors="coerce")
    if "CreatedOnUtc" in rows.columns:
        return pd.to_datetime(rows["CreatedOnUtc"], errors="coerce")
    return pd.Series(pd.NaT, index=rows.index, dtype="datetime64[ns]")


def _prepare_rows(rows: pd.DataFrame) -> pd.DataFrame:
    """Build the small normalized working frame used by both reports."""
    if "AdminComment" not in rows.columns:
        raise ValueError("Input rows are missing required column: AdminComment")

    return pd.DataFrame(
        {
            "AdminComment": rows["AdminComment"],
            "RecordWeight": _record_weights(rows),
            "ValidIPAddress": _valid_ip_addresses(rows),
            "ValidSubnet24": _valid_subnet24_values(rows),
            "CreatedOnUtcDate": _created_on_dates(rows),
        },
        index=rows.index,
    )


def _peak_minute_metrics(
    valid_rows: pd.DataFrame,
    group_column: str,
    output_group_column: str,
) -> pd.DataFrame:
    """Return peak-minute record counts for each infrastructure value."""
    dated_rows = valid_rows.loc[valid_rows["CreatedOnUtcDate"].notna()].copy()
    if dated_rows.empty:
        return pd.DataFrame(
            columns=[output_group_column, "PeakMinuteUtc", "PeakMinuteRecords"]
        )

    dated_rows["MinuteUtc"] = dated_rows["CreatedOnUtcDate"].dt.floor("min")

    # PeakMinuteRecords
    # Description: Highest number of records observed during a single minute.
    # Purpose: Measures the largest traffic burst on the IP or subnet.
    # Calculation: Group by infrastructure value and minute, sum record weights,
    # then return the largest minute-level record count.
    minute_records = (
        dated_rows.groupby([group_column, "MinuteUtc"], dropna=False, sort=False)[
            "RecordWeight"
        ]
        .sum()
        .reset_index(name="PeakMinuteRecords")
    )

    # PeakMinuteUtc
    # Description: The minute with the highest number of records.
    # Purpose: Identifies when the strongest infrastructure burst happened.
    # Calculation: Use the grouped minute totals and keep the highest record
    # count per infrastructure value, breaking ties by earliest minute.
    peak_rows = (
        minute_records.sort_values(
            by=[group_column, "PeakMinuteRecords", "MinuteUtc"],
            ascending=[True, False, True],
        )
        .drop_duplicates(subset=[group_column], keep="first")
        .rename(columns={group_column: output_group_column, "MinuteUtc": "PeakMinuteUtc"})
    )
    return peak_rows[[output_group_column, "PeakMinuteUtc", "PeakMinuteRecords"]]


def _max_concurrent_user_agents(
    valid_rows: pd.DataFrame,
    group_column: str,
    output_group_column: str,
) -> pd.DataFrame:
    """Return the max same-minute distinct User-Agent count per value."""
    dated_rows = valid_rows.loc[valid_rows["CreatedOnUtcDate"].notna()].copy()
    if dated_rows.empty:
        return pd.DataFrame(columns=[output_group_column, "MaxConcurrentUserAgents"])

    dated_rows["MinuteUtc"] = dated_rows["CreatedOnUtcDate"].dt.floor("min")

    # MaxConcurrentUserAgents
    # Description: Maximum number of DISTINCT User-Agents active during the
    # same minute on the same IP or subnet.
    # Purpose: Helps identify coordinated infrastructure where multiple browser
    # identities are active simultaneously.
    # Calculation: Group by infrastructure value and minute, count distinct
    # AdminComment values, then return the maximum count.
    concurrent_counts = (
        dated_rows.groupby([group_column, "MinuteUtc"], dropna=False, sort=False)
        .agg(MaxConcurrentUserAgents=("AdminComment", "nunique"))
        .reset_index()
    )
    result = (
        concurrent_counts.groupby(group_column, dropna=False, sort=False)
        .agg(MaxConcurrentUserAgents=("MaxConcurrentUserAgents", "max"))
        .reset_index()
        .rename(columns={group_column: output_group_column})
    )
    return result[[output_group_column, "MaxConcurrentUserAgents"]]


def analyze_shared_ip(rows: pd.DataFrame) -> pd.DataFrame:
    """Create one infrastructure-sharing row per normalized IP address."""
    if rows.empty:
        return pd.DataFrame(columns=SHARED_IP_INFRASTRUCTURE_COLUMNS)

    working = _prepare_rows(rows)
    valid_ip_rows = working.loc[working["ValidIPAddress"].notna()].copy()
    if valid_ip_rows.empty:
        return pd.DataFrame(columns=SHARED_IP_INFRASTRUCTURE_COLUMNS)

    # IPAddress
    # Description: Normalized first IP address from IPAddress.
    # Purpose: Uses the same first-IP infrastructure key as Per-UA IP Analysis.
    # Calculation: Normalize IPAddress with normalize_ip_address(), trim
    # whitespace, use only the first comma-separated value, and remove invalids.
    #
    # TotalRecords
    # Description: Total number of records using this IP.
    # Purpose: Shows overall observed traffic volume on the IP.
    # Calculation: Group by normalized IPAddress and sum RecordWeight.
    #
    # UniqueUserAgents
    # Description: Number of different User-Agent strings using the same IP.
    # Purpose: Shows how many browser identities share the same infrastructure.
    # Calculation: COUNT(DISTINCT AdminComment) per normalized IPAddress.
    totals = (
        valid_ip_rows.groupby("ValidIPAddress", dropna=False, sort=False)
        .agg(
            TotalRecords=("RecordWeight", "sum"),
            UniqueUserAgents=("AdminComment", "nunique"),
        )
        .reset_index()
        .rename(columns={"ValidIPAddress": "IPAddress"})
    )

    peak = _peak_minute_metrics(valid_ip_rows, "ValidIPAddress", "IPAddress")
    concurrent = _max_concurrent_user_agents(
        valid_ip_rows, "ValidIPAddress", "IPAddress"
    )

    result = totals.merge(peak, on="IPAddress", how="left").merge(
        concurrent, on="IPAddress", how="left"
    )
    result["PeakMinuteRecords"] = result["PeakMinuteRecords"].fillna(0)
    result["MaxConcurrentUserAgents"] = result["MaxConcurrentUserAgents"].fillna(0)
    result = normalize_count_columns(
        result,
        ["TotalRecords", "UniqueUserAgents", "PeakMinuteRecords", "MaxConcurrentUserAgents"],
    )
    return result[SHARED_IP_INFRASTRUCTURE_COLUMNS].sort_values(
        by=["TotalRecords", "UniqueUserAgents", "MaxConcurrentUserAgents"],
        ascending=[False, False, False],
    )


def analyze_shared_subnet24(rows: pd.DataFrame) -> pd.DataFrame:
    """Create one infrastructure-sharing row per normalized /24 subnet."""
    if rows.empty:
        return pd.DataFrame(columns=SHARED_SUBNET24_INFRASTRUCTURE_COLUMNS)

    working = _prepare_rows(rows)
    valid_subnet_rows = working.loc[working["ValidSubnet24"].notna()].copy()
    if valid_subnet_rows.empty:
        return pd.DataFrame(columns=SHARED_SUBNET24_INFRASTRUCTURE_COLUMNS)

    # RangeSubnet24
    # Description: Normalized valid /24 subnet value.
    # Purpose: Uses the same subnet infrastructure key as Per-UA /24 Analysis.
    # Calculation: Trim RangeSubnet24 and remove invalid placeholder values.
    #
    # TotalRecords
    # Description: Total number of records using this subnet.
    # Purpose: Shows overall observed traffic volume on the subnet.
    # Calculation: Group by normalized RangeSubnet24 and sum RecordWeight.
    #
    # UniqueIPs
    # Description: Number of different normalized IP addresses inside this
    # subnet.
    # Purpose: Shows whether subnet activity is spread across many IPs or
    # concentrated on a small set.
    # Calculation: COUNT(DISTINCT normalized first IPAddress) per RangeSubnet24.
    #
    # UniqueUserAgents
    # Description: Number of different User-Agent strings inside this subnet.
    # Purpose: Shows how many browser identities share the same subnet.
    # Calculation: COUNT(DISTINCT AdminComment) per RangeSubnet24.
    totals = (
        valid_subnet_rows.groupby("ValidSubnet24", dropna=False, sort=False)
        .agg(
            TotalRecords=("RecordWeight", "sum"),
            UniqueIPs=("ValidIPAddress", "nunique"),
            UniqueUserAgents=("AdminComment", "nunique"),
        )
        .reset_index()
        .rename(columns={"ValidSubnet24": "RangeSubnet24"})
    )

    peak = _peak_minute_metrics(
        valid_subnet_rows, "ValidSubnet24", "RangeSubnet24"
    )
    concurrent = _max_concurrent_user_agents(
        valid_subnet_rows, "ValidSubnet24", "RangeSubnet24"
    )

    result = totals.merge(peak, on="RangeSubnet24", how="left").merge(
        concurrent, on="RangeSubnet24", how="left"
    )
    result["PeakMinuteRecords"] = result["PeakMinuteRecords"].fillna(0)
    result["MaxConcurrentUserAgents"] = result["MaxConcurrentUserAgents"].fillna(0)
    result = normalize_count_columns(
        result,
        [
            "TotalRecords",
            "UniqueIPs",
            "UniqueUserAgents",
            "PeakMinuteRecords",
            "MaxConcurrentUserAgents",
        ],
    )
    return result[SHARED_SUBNET24_INFRASTRUCTURE_COLUMNS].sort_values(
        by=["TotalRecords", "UniqueUserAgents", "MaxConcurrentUserAgents"],
        ascending=[False, False, False],
    )


def analyze(rows: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Build both infrastructure correlation reports."""
    return {
        SHARED_IP_INFRASTRUCTURE_FILENAME: analyze_shared_ip(rows),
        SHARED_SUBNET24_INFRASTRUCTURE_FILENAME: analyze_shared_subnet24(rows),
    }


def write_reports(rows: pd.DataFrame, output_dir: Path) -> dict[str, int]:
    """Write both infrastructure reports into the provided output folder."""
    output_dir.mkdir(parents=True, exist_ok=True)
    reports = analyze(rows)
    rows_written: dict[str, int] = {}
    for filename, report in reports.items():
        write_dataframe(report, output_dir, filename)
        rows_written[filename] = len(report)
    return rows_written


def main(argv: list[str]) -> int:
    """CLI entry point for standalone infrastructure correlation analysis."""
    if len(argv) not in {2, 3}:
        print(
            "Usage: python Python/infrastructure_correlation_analysis.py "
            '"Results.csv" ["OutputFolder"]',
            file=sys.stderr,
        )
        return 2

    input_path = Path(argv[1])
    output_dir = Path(argv[2]) if len(argv) == 3 else create_output_dir(datetime.now())

    prepared = load_and_prepare_results(input_path)
    rows_written = write_reports(prepared.rows, output_dir)

    print(f"Output folder: {output_dir}")
    for filename, row_count in rows_written.items():
        print(f"{filename}: {row_count} row(s)")

    if prepared.warnings:
        print("Warnings:")
        for warning in prepared.warnings:
            print(f"- {warning}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
