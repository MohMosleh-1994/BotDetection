-- User-Agent Candidate Ranking
-- Generates a ranked list of AdminComment/User-Agent values for investigation.
-- This module does not classify, score, continue, stop, or filter candidates.

WITH Base AS (
    -- Keep every AdminComment record for RecordCount.
    -- Normalize IP/subnet values only for distinct-count metrics.
    SELECT
        AdminComment,
        LTRIM(RTRIM(
            CASE
                WHEN IPAddress IS NULL THEN NULL
                WHEN CHARINDEX(',', IPAddress) > 0
                THEN LEFT(IPAddress, CHARINDEX(',', IPAddress) - 1)
                ELSE IPAddress
            END
        )) AS FirstIPAddress,
        LTRIM(RTRIM(RangeSubnet24)) AS Subnet24,
        LTRIM(RTRIM(RangeSubnet16)) AS Subnet16,
        TRY_CONVERT(datetime2, CreatedOnUtc) AS CreatedOnUtcDate
    FROM Results
    WHERE AdminComment IS NOT NULL
      AND LTRIM(RTRIM(AdminComment)) <> ''
),
Normalized AS (
    -- Exclude invalid values from the specific distinct counts only.
    SELECT
        AdminComment,
        CASE
            WHEN FirstIPAddress IS NULL THEN NULL
            WHEN FirstIPAddress = '' THEN NULL
            WHEN UPPER(FirstIPAddress) IN ('NULL', 'N/A', 'NA', '-') THEN NULL
            ELSE FirstIPAddress
        END AS ValidIPAddress,
        CASE
            WHEN Subnet24 IS NULL THEN NULL
            WHEN Subnet24 = '' THEN NULL
            WHEN UPPER(Subnet24) IN ('NULL', 'N/A', 'NA', '-', '.') THEN NULL
            ELSE Subnet24
        END AS ValidSubnet24,
        CASE
            WHEN Subnet16 IS NULL THEN NULL
            WHEN Subnet16 = '' THEN NULL
            WHEN UPPER(Subnet16) IN ('NULL', 'N/A', 'NA', '-', '.') THEN NULL
            ELSE Subnet16
        END AS ValidSubnet16,
        CreatedOnUtcDate
    FROM Base
),
CandidateRanking AS (
    SELECT
        AdminComment,
        COUNT(*) AS RecordCount,
        COUNT(DISTINCT ValidIPAddress) AS UniqueIPs,
        COUNT(DISTINCT ValidSubnet24) AS UniqueSubnet24,
        COUNT(DISTINCT ValidSubnet16) AS UniqueSubnet16,
        MIN(CreatedOnUtcDate) AS FirstSeenUtc,
        MAX(CreatedOnUtcDate) AS LastSeenUtc
    FROM Normalized
    GROUP BY AdminComment
)
SELECT
    AdminComment,
    RecordCount,
    UniqueIPs,
    UniqueSubnet24,
    UniqueSubnet16,
    FirstSeenUtc,
    LastSeenUtc,
    DATEDIFF(MINUTE, FirstSeenUtc, LastSeenUtc) AS ActiveMinutes
FROM CandidateRanking
ORDER BY
    RecordCount DESC,
    UniqueIPs DESC,
    UniqueSubnet24 DESC,
    ActiveMinutes DESC;
