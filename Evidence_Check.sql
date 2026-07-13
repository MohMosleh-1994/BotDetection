WITH Evidence AS (
    SELECT
        AdminComment,
        COUNT(*) AS RecordCount,

        COUNT(DISTINCT NULLIF(LTRIM(RTRIM(IPAddress)), '')) AS UniqueIPs,
        COUNT(DISTINCT NULLIF(LTRIM(RTRIM(RangeSubnet24)), '')) AS UniqueSubnet24,
        COUNT(DISTINCT NULLIF(LTRIM(RTRIM(RangeSubnet16)), '')) AS UniqueSubnet16,

        MIN(TRY_CONVERT(datetime2, CreatedOnUtc)) AS FirstSeenUtc,
        MAX(TRY_CONVERT(datetime2, CreatedOnUtc)) AS LastSeenUtc,

        DATEDIFF(
            MINUTE,
            MIN(TRY_CONVERT(datetime2, CreatedOnUtc)),
            MAX(TRY_CONVERT(datetime2, CreatedOnUtc))
        ) AS ActiveMinutes
    FROM Results
    WHERE AdminComment IS NOT NULL
      AND LTRIM(RTRIM(AdminComment)) <> ''
      AND TRY_CONVERT(datetime2, CreatedOnUtc) IS NOT NULL
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
    ActiveMinutes,
    CASE
        WHEN RecordCount >= 100
          OR UniqueIPs >= 100
        THEN 'CONTINUE'

        WHEN RecordCount BETWEEN 50 AND 99
          OR UniqueIPs BETWEEN 50 AND 99
        THEN 'BORDERLINE'

        ELSE 'STOP - Insufficient Evidence'
    END AS EvidenceDecision
FROM Evidence
ORDER BY
    CASE
        WHEN RecordCount >= 100 OR UniqueIPs >= 100 THEN 1
        WHEN RecordCount BETWEEN 50 AND 99 OR UniqueIPs BETWEEN 50 AND 99 THEN 2
        ELSE 3
    END,
    RecordCount DESC;
