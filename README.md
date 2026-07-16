# BotDetection

This repository contains SQL and Python helpers for analyzing suspicious
User-Agent patterns from the SQL Server `Results` table.

The Python CSV tools read exported CSV files, parse `AdminComment` User-Agent
strings with `ua-parser`, and write structured CSV output files for review.

## Current Analysis Pipeline

The core SQL investigation flow is:

```text
Results
    ->
User-Agent Candidate Ranking
    ->
(Time Analysis)
(Per-UA IP Analysis)
(Per-UA /24 Analysis)
```

`SQL/00_UserAgent_Candidate_Ranking.sql` ranks `AdminComment` User-Agent values
from highest priority to lowest priority. It does not classify User-Agents and
does not return continue, borderline, or stop decisions.

Global IP, global /24, and global /16 analyses are independent. They continue
to read directly from `Results`.

## Setup

### Windows CMD

```cmd
py -m venv .venv
.venv\Scripts\activate.bat
python -m pip install -r requirements.txt
```

### PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Run Full Analysis Pipeline

The main entry point is:

```cmd
python Python\run_analysis_pipeline.py "Data\Raw\Results.csv"
```

PowerShell:

```powershell
python .\Python\run_analysis_pipeline.py "Data\Raw\Results.csv"
```

The pipeline creates a timestamped folder under `Output/`, runs the approved SQL
analysis scripts, runs the User-Agent structure parser, then automatically
builds final scoring reports.

The scoring builder can also be run by itself against an existing output folder:

```cmd
python Python\build_scoring_reports.py "Output\2026-07-16_123800"
```

## Run User-Agent CSV Analysis

Example input:

```text
Samples/user_agents.csv
```

The input CSV must include:

- `AdminComment`: raw User-Agent string

Optional columns:

- `CleanAdminComment`: cleaned User-Agent pattern
- `RecordCount`: number of records represented by the row

Run from the repository root.

### Windows CMD

```cmd
python Python\ua_csv_analysis.py Samples\user_agents.csv
```

### PowerShell

```powershell
python .\Python\ua_csv_analysis.py .\Samples\user_agents.csv
```

## Outputs

For input `Samples/user_agents.csv`, the script creates:

```text
Output/user_agents_parsed.csv
Output/user_agent_family_summary.csv
```

`Output/user_agents_parsed.csv` writes one row per unique `AdminComment`.
Duplicate User-Agent rows are combined, `RecordCount` is summed, and the file
adds parsed browser, OS, device, version, known/unknown, and structure-decision
fields.

`Output/user_agent_family_summary.csv` groups parsed rows by
`CleanAdminComment`, `BrowserFamily`, `OSFamily`, and `DeviceFamily`.

The script performs structural parsing only. It does not classify a User-Agent
as bot or legitimate.
