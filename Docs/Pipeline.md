# Bot Detection SQL Scripts Overview

## Project Purpose

This project analyzes suspicious website visitors based on User-Agent related
data stored in the SQL Server table `Results`.

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

1. Read candidate traffic from the `Results` table.
2. Run User-Agent Candidate Ranking to order `AdminComment` values from
   highest priority to lowest priority.
3. For selected candidates, run:
   - Time Analysis / Burst Evidence
   - Per-UA IP Analysis
   - Per-UA /24 Analysis
4. Human analyst reviews the combined results.
5. If suspicious, generate a Browscap wildcard candidate.
6. Validate for false positives.
7. Generate Browscap XML rule.

Global IP, global /24, and global /16 analyses remain independent helper
analyses. They read directly from `Results` and do not feed the per-User-Agent
candidate score yet.

## Coverage Analysis

This is a helper/testing script only.

It is not a core decision stage.

It helps inspect related `AdminComment`/User-Agent values, record counts, IP
counts, /24 counts, and /16 counts.

## SQL/00_UserAgent_Candidate_Ranking.sql

### Purpose

Generates a ranked list of `AdminComment`/User-Agent candidates for analyst
investigation.

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

Detects burst behavior for `AdminComment` values.

### Core Idea

A suspicious candidate may have normal low traffic most of the time, then
suddenly spike in a specific minute.

### Main Metrics

- `PeakMinuteUtc`
- `PeakMinuteHits`
- `LocalMedianHits`
- `BurstScore`
- `TimeEvidenceDecision`

### Burst Logic

`BurstScore = PeakMinuteHits / LocalMedianHits`

### Decision Logic

- `LOW EVIDENCE` if `TotalRecords < 100`
- `WORTH CHECKING` if `PeakMinuteHits >= 100` AND `BurstScore >= 20`
- `LOW BURST` otherwise

### Important

The analysis should use minute-level grouping based on `CreatedOnUtc`.

Use `TRY_CONVERT(datetime2, CreatedOnUtc)` to avoid conversion errors.

## 03_Network_Analysis_IP.sql

### Purpose

Detects whether one IP address dominates traffic for an `AdminComment`.

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
- `IPEvidenceDecision`

### Decision Logic

- `LOW EVIDENCE` if `TotalRecords < 100` AND `UniqueIPs < 100`
- `WORTH CHECKING` if `TopIPCoverageFromValidIPRecordsPercent >= 20`
- `LOW IP CONCENTRATION` otherwise

### Important

`TotalRecords` must count all records.

`RecordsWithIP` excludes only invalid IP values.

Invalid IP values include real `NULL`, empty string, `NULL`, `N/A`, `NA`, and
`-`.

## 03_Network_Analysis_Subnet24.sql

### Purpose

Detects whether one /24 subnet dominates traffic for an `AdminComment`.

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

### Decision Logic

- `LOW EVIDENCE` if `TotalRecords < 100` AND `UniqueSubnet24 < 100`
- `WORTH CHECKING` if `TopSubnet24CoverageFromValidSubnet24RecordsPercent >= 20`
- `LOW /24 CONCENTRATION` otherwise

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

Planned future enhancement.

It should combine evidence from:

- User-Agent Candidate Ranking volume and coverage context
- Time/Burst behavior
- Network concentration
- Representative User-Agent stability
- False-positive risk

Do not implement scoring until all core analysis modules are stable.
