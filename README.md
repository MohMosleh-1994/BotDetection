# BotDetection

This repository contains SQL and Python helpers for analyzing suspicious
User-Agent patterns from the SQL Server `Results` table.

The Python CSV tool does not connect to SQL Server. It reads exported CSV files,
parses `AdminComment` User-Agent strings with `ua-parser`, and writes structured
CSV output files for review.

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
