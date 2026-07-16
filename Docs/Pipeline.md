# Bot Detection SQL Scripts Overview

## Project Purpose

This project analyzes suspicious website visitors based on User-Agent related
data exported from the `Results` table into `Results.csv`.

## Main Table

`Results`

## Important Columns

- `AdminComment`: original User-Agent string. This is the current primary
  analysis key.
- `CleanAdminComment`: normalized / cleaned User-Agent pattern. This can be
  kept as supporting context, but it is not the current primary analysis key.
- `IPAddress`: visitor IP address. Sometimes it may contain multiple IPs
  separated by comma; when analyzing IPs, use the first IP only.
- `RangeSubnet24`: /24 subnet value.
- `RangeSubnet16`: /16 subnet value. Used only as optional information, not as
  a primary decision signal.
- `CreatedOnUtc`: request timestamp.
- `CustomerId`, `StoreId`, `CheckIPLink`: supporting columns if needed.
- `ASN` is not available and must not be used.

## General Rule

Do not exclude a full record from `RecordCount` just because `IPAddress`,
`RangeSubnet24`, or `RangeSubnet16` is `NULL` or empty.

Only exclude null/empty values from the specific distinct-count or concentration
calculation where that field is required.

## Current Practical Pipeline

1. Read `Results.csv` once in `run_analysis_pipeline.py`.
2. Normalize shared columns once into a prepared pandas DataFrame.
3. Run User-Agent Candidate Ranking to order `AdminComment` values from
   highest priority to lowest priority.
4. Run the in-memory Python analysis modules:
   - Time Analysis / Burst Evidence
   - Per-UA IP Analysis
   - Per-UA /24 Analysis
   - Global IP Analysis
   - Global /24 Analysis
   - Global /16 Analysis
5. Run User-Agent structure analysis.
6. Run final scoring report generation.
7. Human analyst reviews the combined results.
8. If suspicious, generate a Browscap wildcard candidate.
9. Validate for false positives.
10. Generate Browscap XML rule.

The `.sql` files are retained as reference/manual SQL scripts. They are not
executed by the active Python pipeline.

Global IP, global /24, and global /16 analyses remain independent helper
analyses. They use the same prepared pandas DataFrame and do not feed the
per-User-Agent candidate score yet.

## Coverage Analysis

This is a helper/testing script only.

It is not a core decision stage.

It helps inspect related `AdminComment`/User-Agent values, record counts, IP
counts, /24 counts, and /16 counts.

## SQL/00_UserAgent_Candidate_Ranking.sql

### Purpose

Reference SQL script for the ranked list of `AdminComment`/User-Agent
candidates. The active pipeline implementation is
`Python/candidate_ranking.py`.

This module is not a decision gate. It does not classify candidates, and it
does not return continue, borderline, or stop decisions.

### Main Output

- `AdminComment`
- `RecordCount`
- `UniqueIPs`
- `UniqueSubnet24`
- `UniqueSubnet16`
- `FirstSeenUtc`
- `LastSeenUtc`
- `ActiveMinutes`

### Sort Order

1. `RecordCount DESC`
2. `UniqueIPs DESC`
3. `UniqueSubnet24 DESC`
4. `ActiveMinutes DESC`

### Important

Use `AdminComment` as the candidate key.

Do not use `CleanAdminComment` in this module.

Do not calculate any candidate decision value.

`RecordCount` is used for ranking and analyst context only. It is not included
in `SuspicionScore`.

## 01_Coverage_Analysis.sql

### Purpose

Helper script for manual investigation and testing.

It shows top original `AdminComment`/User-Agent values and related network
distribution.

### Expected Sections

- Top 20 `AdminComment`/User-Agent values
- Top IP addresses
- Top /24 subnets
- Top /16 subnets

### Important

Coverage Analysis is useful for exploration but should not be treated as a core
pipeline decision step.

## 02_Time_Analysis.sql

### Purpose

Reference SQL script for burst behavior. The active pipeline implementation is
`Python/time_analysis.py`.

### Core Idea

A suspicious candidate may have normal low traffic most of the time, then
suddenly spike in a specific minute.

### Main Metrics

- `PeakMinuteUtc`
- `PeakMinuteHits`
- `LocalMedianHits`
- `BurstScore`
- `PeakVolumeScore`
- `BurstScoreValue`
- `TimeScore`
- `TimePriority`

### Burst Logic

`BurstScore = PeakMinuteHits / LocalMedianHits`

### Scoring Logic

`PeakVolumeScore`, maximum 10:

- `PeakMinuteHits < 50` = 0
- `50 to 74` = 2
- `75 to 99` = 4
- `100 to 149` = 7
- `150 or more` = 10

`BurstScoreValue`, maximum 5:

- `BurstScore < 2` = 0
- `2 to less than 5` = 1
- `5 to less than 10` = 2
- `10 to less than 20` = 3
- `20 to less than 40` = 4
- `40 or more` = 5

`TimeScore = PeakVolumeScore + BurstScoreValue`

Maximum `TimeScore` is 15.

### Important

The analysis should use minute-level grouping based on `CreatedOnUtc`.

Use `TRY_CONVERT(datetime2, CreatedOnUtc)` to avoid conversion errors.

## 03_Network_Analysis_IP.sql

### Purpose

Reference SQL script for IP concentration. The active pipeline implementation is
`Python/ip_analysis.py`.

### Important IP Rule

If `IPAddress` contains multiple IPs separated by comma, use only the first IP.

### Main Output

- `AdminComment`
- `TotalRecords`
- `RecordsWithIP`
- `UniqueIPs`
- `TopIPAddress`
- `TopIPRecords`
- `TopIPCoverageFromTotalRecordsPercent`
- `TopIPCoverageFromValidIPRecordsPercent`
- `IPConcentrationScore`
- `IPVolumeScore`
- `IPScore`
- `IPPriority`
- `IPScoreReason`

### Scoring Logic

If `TotalRecords < 100`:

- `IPScore = 0`
- `IPScoreReason = Insufficient sample size`

Otherwise:

- calculate `IPConcentrationScore` from 0 to 5
- calculate `IPVolumeScore` from 0 to 5 using `TopIPRecords`
- if coverage is less than 5%, `IPScore = 0` and the reason is
  `No meaningful IP concentration`
- otherwise, `IPScore = IPConcentrationScore + IPVolumeScore`

### Important

`TotalRecords` must count all records.

`RecordsWithIP` excludes only invalid IP values.

Invalid IP values include real `NULL`, empty string, `NULL`, `N/A`, `NA`, and
`-`.

## 03_Network_Analysis_Subnet24.sql

### Purpose

Reference SQL script for /24 concentration. The active pipeline implementation
is `Python/subnet24_analysis.py`.

### Main Output

- `AdminComment`
- `TotalRecords`
- `RecordsWithSubnet24`
- `UniqueSubnet24`
- `TopSubnet24`
- `TopSubnet24Records`
- `TopSubnet24CoverageFromTotalRecordsPercent`
- `TopSubnet24CoverageFromValidSubnet24RecordsPercent`
- `Subnet24EvidenceDecision`
- `Subnet24Score`

### Decision Logic

- `LOW EVIDENCE` if `TotalRecords < 100` AND `UniqueSubnet24 < 100`
- `WORTH CHECKING` if `TopSubnet24CoverageFromValidSubnet24RecordsPercent >= 20`
- `LOW /24 CONCENTRATION` otherwise

### Temporary Score Mapping

- `WORTH CHECKING` = 10
- `LOW /24 CONCENTRATION` = 0
- `LOW EVIDENCE` = 0

### Invalid /24 Values

Real `NULL`, empty string, `NULL`, `N/A`, `NA`, `-`, `.`

### /16 Subnet Note

`RangeSubnet16` may be calculated for context only.

Do not use /16 as a primary evidence metric or scoring signal in v1.

It is too broad and may produce misleading 100% concentration when only a small
number of valid /16 records exists.

## Representative User-Agent Analysis

Not fully implemented yet.

### Goal

Use the analyzed `AdminComment`/User-Agent as the candidate value for safe
Browscap wildcard generation.

### Future Goals

- Identify dominant `AdminComment`/User-Agent
- Calculate UA coverage percentage
- Detect if one UA family dominates
- Detect version stability
- Generate a candidate Browscap wildcard
- Validate false positives
- Generate Browscap XML

## Scoring System

The active final scoring report combines evidence from:

- Time/Burst behavior
- Network concentration
- Representative User-Agent stability
- False-positive risk remains a human-review consideration.

Candidate Ranking volume and spread fields are ranking/context only. They are
not part of `SuspicionScore`.

`SuspicionScore = TimeScore + IPScore + Subnet24Score + UAStructureScore`

Maximum `SuspicionScore` is 45.

Final decision ranges:

- `0 to 9` = `LOW`
- `10 to 19` = `REVIEW`
- `20 to 29` = `HIGH`
- `30 to 45` = `CRITICAL`
