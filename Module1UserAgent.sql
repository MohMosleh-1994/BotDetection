--User Agent top 20

SELECT TOP 20
    CleanAdminComment,
    COUNT(*) AS RecordsCount,
    COUNT(DISTINCT IPAddress) AS UniqueIPs,
    COUNT(DISTINCT RangeSubnet24) AS UniqueSubnet24,
    COUNT(DISTINCT RangeSubnet16) AS UniqueSubnet16,
    MIN(TRY_CONVERT(datetime2, CreatedOnUtc)) AS FirstSeen,
    MAX(TRY_CONVERT(datetime2, CreatedOnUtc)) AS LastSeen
FROM Results
WHERE CleanAdminComment IS NOT NULL
  AND LTRIM(RTRIM(CleanAdminComment)) <> ''
  AND TRY_CONVERT(datetime2, CreatedOnUtc) IS NOT NULL
GROUP BY CleanAdminComment
ORDER BY RecordsCount DESC;


