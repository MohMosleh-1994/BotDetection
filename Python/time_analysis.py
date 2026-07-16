"""Run in-memory per-User-Agent time and burst analysis."""

from __future__ import annotations

import pandas as pd

from pipeline_common import normalize_count_columns, safe_ratio


WINDOW_MINUTES = 5

TIME_ANALYSIS_COLUMNS = [
    "AdminComment",
    "TotalRecords",
    "RecordsWithValidDate",
    "PeakMinuteUtc",
    "PeakMinuteHits",
    "LocalMedianHits",
    "BurstScore",
    "PeakVolumeScore",
    "BurstScoreValue",
    "TimeScore",
    "TimePriority",
]


def peak_volume_score(peak_minute_hits: float) -> int:
    """Score peak-minute volume from 0 to 10."""
    if peak_minute_hits < 50:
        return 0
    if peak_minute_hits < 75:
        return 2
    if peak_minute_hits < 100:
        return 4
    if peak_minute_hits < 150:
        return 7
    return 10


def burst_score_value(burst_score: float) -> int:
    """Score burst ratio from 0 to 5."""
    if burst_score < 2:
        return 0
    if burst_score < 5:
        return 1
    if burst_score < 10:
        return 2
    if burst_score < 20:
        return 3
    if burst_score < 40:
        return 4
    return 5


def time_priority(time_score: int) -> str:
    """Convert the 0-15 time score into a priority label."""
    if time_score >= 13:
        return "VERY HIGH"
    if time_score >= 10:
        return "HIGH"
    if time_score >= 7:
        return "MEDIUM"
    if time_score >= 4:
        return "LOW"
    return "VERY LOW"


def analyze(rows: pd.DataFrame) -> pd.DataFrame:
    """Calculate minute-level burst metrics for every AdminComment."""
    if rows.empty:
        return pd.DataFrame(columns=TIME_ANALYSIS_COLUMNS)

    working = rows[["AdminComment", "_RecordWeight", "CreatedOnUtcDate"]].copy()
    working["ValidDateWeight"] = working["_RecordWeight"].where(
        working["CreatedOnUtcDate"].notna(), 0
    )

    totals = (
        working.groupby("AdminComment", dropna=False, sort=False)
        .agg(
            TotalRecords=("_RecordWeight", "sum"),
            RecordsWithValidDate=("ValidDateWeight", "sum"),
        )
        .reset_index()
    )

    valid_dates = working.loc[working["CreatedOnUtcDate"].notna()].copy()
    if not valid_dates.empty:
        valid_dates["MinuteUtc"] = valid_dates["CreatedOnUtcDate"].dt.floor("min")
        minute_hits = (
            valid_dates.groupby(["AdminComment", "MinuteUtc"], dropna=False, sort=False)[
                "_RecordWeight"
            ]
            .sum()
            .reset_index(name="Hits")
        )

        peak = (
            minute_hits.sort_values(
                by=["AdminComment", "Hits", "MinuteUtc"],
                ascending=[True, False, True],
            )
            .drop_duplicates(subset=["AdminComment"], keep="first")
            .rename(columns={"MinuteUtc": "PeakMinuteUtc", "Hits": "PeakMinuteHits"})
        )

        local_window = minute_hits.merge(
            peak[["AdminComment", "PeakMinuteUtc", "PeakMinuteHits"]],
            on="AdminComment",
            how="inner",
        )
        window_start = local_window["PeakMinuteUtc"] - pd.Timedelta(minutes=WINDOW_MINUTES)
        window_end = local_window["PeakMinuteUtc"] + pd.Timedelta(minutes=WINDOW_MINUTES)
        local_window = local_window.loc[
            (local_window["MinuteUtc"] >= window_start)
            & (local_window["MinuteUtc"] <= window_end)
        ]

        median = (
            local_window.groupby(
                ["AdminComment", "PeakMinuteUtc", "PeakMinuteHits"],
                dropna=False,
                sort=False,
            )["Hits"]
            .median()
            .reset_index(name="LocalMedianHits")
        )
    else:
        median = pd.DataFrame(
            columns=["AdminComment", "PeakMinuteUtc", "PeakMinuteHits", "LocalMedianHits"]
        )

    result = totals.merge(median, on="AdminComment", how="left")
    result["BurstScore"] = safe_ratio(result["PeakMinuteHits"], result["LocalMedianHits"])
    result["PeakVolumeScore"] = (
        pd.to_numeric(result["PeakMinuteHits"], errors="coerce")
        .fillna(0)
        .map(peak_volume_score)
    )
    result["BurstScoreValue"] = (
        pd.to_numeric(result["BurstScore"], errors="coerce")
        .fillna(0)
        .map(burst_score_value)
    )
    result["TimeScore"] = result["PeakVolumeScore"] + result["BurstScoreValue"]
    result["TimePriority"] = result["TimeScore"].map(time_priority)

    result = normalize_count_columns(
        result,
        [
            "TotalRecords",
            "RecordsWithValidDate",
            "PeakMinuteHits",
            "PeakVolumeScore",
            "BurstScoreValue",
            "TimeScore",
        ],
    )
    result["LocalMedianHits"] = pd.to_numeric(
        result["LocalMedianHits"], errors="coerce"
    ).round(2)
    result["BurstScore"] = pd.to_numeric(result["BurstScore"], errors="coerce").round(2)

    return result[TIME_ANALYSIS_COLUMNS].sort_values(
        by=["TimeScore", "PeakMinuteHits", "BurstScore", "TotalRecords"],
        ascending=[False, False, False, False],
    )
