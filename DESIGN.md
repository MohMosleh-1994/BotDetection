# BotDetection Design

## Core Data Source

The project analyzes User-Agent activity from the SQL Server `Results` table.

`AdminComment` is the raw User-Agent string and is the primary per-User-Agent
analysis key.

`CleanAdminComment` can be useful supporting context, but it is not used as the
candidate key in the current per-User-Agent pipeline.

## Core Pipeline

```text
Results
    ↓
User-Agent Candidate Ranking
    ↓
(Time Analysis)
(Per-UA IP Analysis)
(Per-UA /24 Analysis)
```

## User-Agent Candidate Ranking

`SQL/00_UserAgent_Candidate_Ranking.sql` creates a ranked candidate table for
analyst investigation.

The module returns volume, IP spread, subnet spread, and active time fields per
`AdminComment`. It does not classify candidates and does not decide whether a
candidate should continue or stop.

Analysts use this ranked table to choose which User-Agent values should be
investigated first.

## Per-User-Agent Analyses

Time Analysis, Per-UA IP Analysis, and Per-UA /24 Analysis all use
`AdminComment` as their per-User-Agent key.

Each analysis reads from `Results` and produces evidence that can be reviewed
alongside the candidate ranking output.

## Global Analyses

Global IP, global /24, and global /16 analyses remain independent. They read
directly from `Results` and are not part of the per-User-Agent ranking stage.
