--CleanAgent code with uniqueIP firstseen last seen active minutes recordes perminutes 
SELECT
    CleanAdminComment,
    COUNT(*) AS RecordsCount,
    COUNT(DISTINCT IPAddress) AS UniqueIPs,
    MIN(TRY_CONVERT(datetime2, CreatedOnUtc)) AS FirstSeen,
    MAX(TRY_CONVERT(datetime2, CreatedOnUtc)) AS LastSeen,
    DATEDIFF(
        MINUTE,
        MIN(TRY_CONVERT(datetime2, CreatedOnUtc)),
        MAX(TRY_CONVERT(datetime2, CreatedOnUtc))
    ) AS ActiveMinutes,
    COUNT(*) * 1.0 / NULLIF(
        DATEDIFF(
            MINUTE,
            MIN(TRY_CONVERT(datetime2, CreatedOnUtc)),
            MAX(TRY_CONVERT(datetime2, CreatedOnUtc))
        ),
        0
    ) AS RecordsPerMinute
FROM Results
WHERE CleanAdminComment IS NOT NULL
  AND LTRIM(RTRIM(CleanAdminComment)) <> ''
  AND TRY_CONVERT(datetime2, CreatedOnUtc) IS NOT NULL
GROUP BY CleanAdminComment
ORDER BY RecordsPerMinute DESC;






--Time Line 

DECLARE @UserAgent NVARCHAR(MAX);

SET @UserAgent = N'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36';

SELECT
    CONVERT(VARCHAR(16), TRY_CONVERT(datetime2, CreatedOnUtc), 120) AS ActivityMinute,
    COUNT(*) AS Hits
FROM Results
WHERE AdminComment = @UserAgent
  AND TRY_CONVERT(datetime2, CreatedOnUtc) IS NOT NULL
GROUP BY
    CONVERT(VARCHAR(16), TRY_CONVERT(datetime2, CreatedOnUtc), 120)
ORDER BY
    ActivityMinute;






    ---IPADD Between Appears In time range 
SELECT
    IPAddress,
    COUNT(*) AS Records
FROM Results
WHERE AdminComment = 'Mozilla/5.0 (Windows NT 6.3; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36'
  AND TRY_CONVERT(datetime2, CreatedOnUtc) >= '2026-06-29 02:14:00.000'
  AND TRY_CONVERT(datetime2, CreatedOnUtc) <  '2026-06-29 02:30:00.000'
GROUP BY IPAddress
ORDER BY Records DESC;

