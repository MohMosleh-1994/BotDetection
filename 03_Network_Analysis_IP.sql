-- Network Analysis - IP Evidence
-- Runs across all AdminComment values and detects IP concentration.

WITH Base AS (
    -- Keep every record for TotalRecords; only normalize IP for IP-specific metrics.
    SELECT
        AdminComment,
        LTRIM(RTRIM(
            CASE
                WHEN IPAddress IS NULL THEN NULL
                WHEN CHARINDEX(',', IPAddress) > 0
                THEN LEFT(IPAddress, CHARINDEX(',', IPAddress) - 1)
                ELSE IPAddress
            END
        )) AS FirstIPAddress
    FROM Results
    WHERE AdminComment IS NOT NULL
      AND LTRIM(RTRIM(AdminComment)) <> ''
),
Normalized AS (
    -- Exclude only invalid IP values from IP calculations.
    SELECT
        AdminComment,
        CASE
            WHEN FirstIPAddress IS NULL THEN NULL
            WHEN FirstIPAddress = '' THEN NULL
            WHEN UPPER(FirstIPAddress) IN ('NULL', 'N/A', 'NA', '-') THEN NULL
            ELSE FirstIPAddress
        END AS ValidIPAddress
    FROM Base
),
CandidateTotals AS (
    -- TotalRecords counts all records, even when IPAddress is missing or invalid.
    SELECT
        AdminComment,
        COUNT(*) AS TotalRecords,
        COUNT(ValidIPAddress) AS RecordsWithIP,
        COUNT(DISTINCT ValidIPAddress) AS UniqueIPs
    FROM Normalized
    GROUP BY AdminComment
),
IPCounts AS (
    -- Count valid IP usage per AdminComment.
    SELECT
        AdminComment,
        ValidIPAddress,
        COUNT(*) AS IPRecords
    FROM Normalized
    WHERE ValidIPAddress IS NOT NULL
    GROUP BY
        AdminComment,
        ValidIPAddress
),
TopIP AS (
    -- Pick the most common valid IP for each AdminComment.
    SELECT
        AdminComment,
        ValidIPAddress AS TopIPAddress,
        IPRecords AS TopIPRecords,
        ROW_NUMBER() OVER (
            PARTITION BY AdminComment
            ORDER BY IPRecords DESC, ValidIPAddress ASC
        ) AS rn
    FROM IPCounts
),
Metrics AS (
    -- Calculate concentration percentages before assigning component scores.
    SELECT
        c.AdminComment,
        c.TotalRecords,
        c.RecordsWithIP,
        c.UniqueIPs,
        t.TopIPAddress,
        COALESCE(t.TopIPRecords, 0) AS TopIPRecords,
        CAST(
            COALESCE(t.TopIPRecords, 0) * 100.0 / NULLIF(c.TotalRecords, 0)
            AS DECIMAL(10,2)
        ) AS TopIPCoverageFromTotalRecordsPercent,
        CAST(
            COALESCE(t.TopIPRecords, 0) * 100.0 / NULLIF(c.RecordsWithIP, 0)
            AS DECIMAL(10,2)
        ) AS TopIPCoverageFromValidIPRecordsPercent
    FROM CandidateTotals c
    LEFT JOIN TopIP t
        ON t.AdminComment = c.AdminComment
       AND t.rn = 1
),
ComponentScores AS (
    -- Score concentration from 0-5 using gradual coverage bands.
    -- Score volume from 0-5 using simple TopIPRecords ranges, but only when
    -- there are at least 100 total records for a meaningful sample size.
    SELECT
        AdminComment,
        TotalRecords,
        RecordsWithIP,
        UniqueIPs,
        TopIPAddress,
        TopIPRecords,
        TopIPCoverageFromTotalRecordsPercent,
        TopIPCoverageFromValidIPRecordsPercent,
        CASE
            WHEN COALESCE(TopIPCoverageFromValidIPRecordsPercent, 0) < 5 THEN 0
            WHEN TopIPCoverageFromValidIPRecordsPercent < 10 THEN 1
            WHEN TopIPCoverageFromValidIPRecordsPercent < 20 THEN 2
            WHEN TopIPCoverageFromValidIPRecordsPercent < 30 THEN 3
            WHEN TopIPCoverageFromValidIPRecordsPercent < 50 THEN 4
            ELSE 5
        END AS IPConcentrationScore,
        CASE
            WHEN TotalRecords < 100 THEN 0
            WHEN TopIPRecords < 10 THEN 0
            WHEN TopIPRecords < 25 THEN 1
            WHEN TopIPRecords < 50 THEN 2
            WHEN TopIPRecords < 100 THEN 3
            WHEN TopIPRecords < 200 THEN 4
            ELSE 5
        END AS IPVolumeScore
    FROM Metrics
),
Scored AS (
    -- Samples below 100 total records do not receive a meaningful final score.
    -- Otherwise, combine the two 0-5 components into the final 0-10 score.
    SELECT
        *,
        CASE
            WHEN TotalRecords < 100 THEN 0
            ELSE IPConcentrationScore + IPVolumeScore
        END AS IPScore
    FROM ComponentScores
),
Final AS (
    SELECT
        *,
        CASE
            WHEN IPScore >= 8 THEN 'HIGH'
            WHEN IPScore >= 5 THEN 'MEDIUM'
            ELSE 'LOW'
        END AS IPPriority,
        CASE
            WHEN TotalRecords < 100 THEN 'Insufficient sample size'
            WHEN IPConcentrationScore >= 4 AND IPVolumeScore >= 4
                THEN 'High concentration + High volume'
            WHEN IPConcentrationScore >= 4 THEN 'High concentration'
            WHEN IPVolumeScore >= 4 THEN 'High volume'
            WHEN IPConcentrationScore > IPVolumeScore THEN 'Concentration-driven score'
            WHEN IPVolumeScore > IPConcentrationScore THEN 'Volume-driven score'
            ELSE 'Low concentration and volume'
        END AS IPScoreReason
    FROM Scored
)
SELECT
    AdminComment,
    TotalRecords,
    RecordsWithIP,
    UniqueIPs,
    TopIPAddress,
    TopIPRecords,
    TopIPCoverageFromTotalRecordsPercent,
    TopIPCoverageFromValidIPRecordsPercent,
    IPConcentrationScore,
    IPVolumeScore,
    IPScore,
    IPPriority,
    IPScoreReason
FROM Final
ORDER BY
    IPScore DESC,
    TopIPCoverageFromValidIPRecordsPercent DESC,
    TopIPRecords DESC,
    TotalRecords DESC;
