# BotDetection

This repository contains SQL references and Python helpers for analyzing
suspicious User-Agent patterns from exported `Results.csv` data.

The active pipeline reads one exported CSV file into pandas, runs independent
Python analysis modules, parses `AdminComment` User-Agent strings with
`ua-parser`, and writes structured CSV output files for review.

## Current Analysis Pipeline

The core investigation flow is:

```text
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

`run_analysis_pipeline.py` is the main entry point. It reads the input CSV once,
normalizes shared columns once, then passes the same prepared pandas DataFrame
to each module.

The `.sql` files are kept as reference scripts for manual SQL review. They are
not executed by the active Python pipeline.

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

The pipeline creates one timestamped folder under `Output/`, runs the in-memory
analysis modules, runs the User-Agent structure parser, then automatically
builds final scoring reports.

The scoring builder can also be run by itself against an existing output folder:

```cmd
python Python\build_scoring_reports.py "Output\2026-07-16_123800"
```

The full pipeline writes these output files into the timestamped output folder:

- `Candidate_Summary.csv`
- `Time_Analysis.csv`
- `PerUA_IP_Analysis.csv`
- `PerUA_Subnet24_Analysis.csv`
- `Global_IP_Analysis.csv`
- `Global_Subnet24_Analysis.csv`
- `Global_Subnet16_Analysis.csv`
- `UA_Structure_Analysis.csv`
- `Final_Suspicious_Report.csv`
- `Final_Review_Queue.csv`
- `Global_Investigation_Report.csv`
- `Run_Summary.txt`

The final `SuspicionScore` does not include `RecordCount`, `VolumeScore`, or
`UAStructureScore`.
It is calculated as:

```text
TimeScore + IPScore + Subnet24Score
```

The maximum score is 35. User-Agent structure fields remain visible for analyst
context, but they do not increase suspicion by themselves.

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
