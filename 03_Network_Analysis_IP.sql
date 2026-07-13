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
Final AS (
    -- Calculate concentration percentages and the IP evidence decision.
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
        ) AS TopIPCoverageFromValidIPRecordsPercent,
        CASE
            WHEN c.TotalRecords < 100
             AND c.UniqueIPs < 100
            THEN 'LOW EVIDENCE'

            WHEN COALESCE(t.TopIPRecords, 0) * 100.0 / NULLIF(c.RecordsWithIP, 0) >= 20
            THEN 'WORTH CHECKING'

            ELSE 'LOW IP CONCENTRATION'
        END AS IPEvidenceDecision
    FROM CandidateTotals c
    LEFT JOIN TopIP t
        ON t.AdminComment = c.AdminComment
       AND t.rn = 1
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
    IPEvidenceDecision
FROM Final
ORDER BY
    CASE
        WHEN IPEvidenceDecision = 'WORTH CHECKING' THEN 1
        WHEN IPEvidenceDecision = 'LOW IP CONCENTRATION' THEN 2
        WHEN IPEvidenceDecision = 'LOW EVIDENCE' THEN 3
        ELSE 4
    END,
    TopIPCoverageFromValidIPRecordsPercent DESC;
