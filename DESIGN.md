# BotDetection Design

## Core Data Source

The active pipeline analyzes User-Agent activity from an exported `Results.csv`
file. SQL scripts remain in the repository as manual reference scripts.

`AdminComment` is the raw User-Agent string and is the primary per-User-Agent
analysis key.

`CleanAdminComment` can be useful supporting context, but it is not used as the
candidate key in the current per-User-Agent pipeline.

## Core Pipeline

```text
Results
    ->
Results.csv
    ->
User-Agent Candidate Ranking
    ->
(Time Analysis)
(Per-UA IP Analysis)
(Per-UA /24 Analysis)
(Global IP Analysis)
(Global /24 Analysis)
(Global /16 Analysis)
    ->
User-Agent Structure Analysis
    ->
Final Scoring Reports
```

`run_analysis_pipeline.py` reads `Results.csv` once, normalizes shared columns
once, and passes the same prepared pandas DataFrame to each analysis module.

## User-Agent Candidate Ranking

`Python/candidate_ranking.py` creates a ranked candidate table for analyst
investigation. `SQL/00_UserAgent_Candidate_Ranking.sql` is kept as the manual
SQL reference for the same concept.

The module returns volume, IP spread, subnet spread, and active time fields per
`AdminComment`. It does not classify candidates and does not decide whether a
candidate should continue or stop.

Analysts use this ranked table to choose which User-Agent values should be
investigated first.

`RecordCount` is a ranking/context metric only. It is not suspicion evidence and
is not included in the final score.

## Per-User-Agent Analyses

Time Analysis, Per-UA IP Analysis, and Per-UA /24 Analysis all use
`AdminComment` as their per-User-Agent key.

Each analysis receives the same prepared DataFrame and produces evidence that
can be reviewed alongside the candidate ranking output.

## Global Analyses

Global IP, global /24, and global /16 analyses remain independent. They use the
same prepared DataFrame and are not part of the per-User-Agent ranking stage.

## Final Scoring

`SuspicionScore` uses only per-User-Agent evidence scores:

```text
SuspicionScore = TimeScore + IPScore + Subnet24Score + UAStructureScore
```

The maximum score is 45. Final decisions use:

- `0 to 9`: `LOW`
- `10 to 19`: `REVIEW`
- `20 to 29`: `HIGH`
- `30 to 45`: `CRITICAL`
