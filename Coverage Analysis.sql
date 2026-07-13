--Top 20 User Agent

SELECT TOP 20
    AdminComment,
    COUNT(*) AS RecordsCount,
    COUNT(DISTINCT IPAddress) AS UniqueIPs,
    COUNT(DISTINCT RangeSubnet24) AS UniqueSubnet24,
    COUNT(DISTINCT RangeSubnet16) AS UniqueSubnet16,
    MIN(TRY_CONVERT(datetime2, CreatedOnUtc)) AS FirstSeen,
    MAX(TRY_CONVERT(datetime2, CreatedOnUtc)) AS LastSeen
FROM Results
WHERE AdminComment IS NOT NULL
  AND LTRIM(RTRIM(AdminComment)) <> ''
  AND TRY_CONVERT(datetime2, CreatedOnUtc) IS NOT NULL
GROUP BY AdminComment
ORDER BY RecordsCount DESC;





--Top IPADD

SELECT
    IPAddress,
    COUNT(*) AS RecordsCount,
    COUNT(DISTINCT AdminComment) AS UniqueUserAgents,
    COUNT(DISTINCT RangeSubnet24) AS UniqueSubnet24,
    MIN(TRY_CONVERT(datetime2, CreatedOnUtc)) AS FirstSeen,
    MAX(TRY_CONVERT(datetime2, CreatedOnUtc)) AS LastSeen
FROM Results
WHERE IPAddress IS NOT NULL
  AND AdminComment IS NOT NULL
  AND TRY_CONVERT(datetime2, CreatedOnUtc) IS NOT NULL
GROUP BY IPAddress
ORDER BY RecordsCount DESC;



--TOP 24 Subnet

SELECT
    RangeSubnet24,
    COUNT(*) AS RecordsCount,
    COUNT(DISTINCT IPAddress) AS UniqueIPs,
    COUNT(DISTINCT AdminComment) AS UniqueUserAgents,
    MIN(TRY_CONVERT(datetime2, CreatedOnUtc)) AS FirstSeen,
    MAX(TRY_CONVERT(datetime2, CreatedOnUtc)) AS LastSeen
FROM Results
WHERE RangeSubnet24 IS NOT NULL
  AND TRY_CONVERT(datetime2, CreatedOnUtc) IS NOT NULL
GROUP BY RangeSubnet24
ORDER BY RecordsCount DESC;



--Top 16 Subnet 

SELECT
    RangeSubnet16,
    COUNT(*) AS RecordsCount,
    COUNT(DISTINCT IPAddress) AS UniqueIPs,
    COUNT(DISTINCT AdminComment) AS UniqueUserAgents,
    MIN(TRY_CONVERT(datetime2, CreatedOnUtc)) AS FirstSeen,
    MAX(TRY_CONVERT(datetime2, CreatedOnUtc)) AS LastSeen
FROM Results
WHERE RangeSubnet16 IS NOT NULL
  AND TRY_CONVERT(datetime2, CreatedOnUtc) IS NOT NULL
GROUP BY RangeSubnet16
ORDER BY RecordsCount DESC;
