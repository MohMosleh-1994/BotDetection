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





--Burstscore

DECLARE @CleanAdminComment NVARCHAR(500) =
    'Mozilla/(Linux;Android;PixelPro)AppleWebKit/(KHTML,likeGecko)Chrome/MobileSafari/OPR/';

DECLARE @WindowMinutes INT = 5;

WITH Base AS (
    SELECT
        AdminComment AS UserAgent,
        TRY_CONVERT(datetime2, CreatedOnUtc) AS CreatedOnUtcDate
    FROM Results
    WHERE CleanAdminComment = @CleanAdminComment
      AND AdminComment IS NOT NULL
      AND LTRIM(RTRIM(AdminComment)) <> ''
      AND CreatedOnUtc IS NOT NULL
),
ValidDates AS (
    SELECT
        UserAgent,
        CreatedOnUtcDate
    FROM Base
    WHERE CreatedOnUtcDate IS NOT NULL
),
MinuteHits AS (
    SELECT
        UserAgent,
        DATEADD(
            MINUTE,
            DATEDIFF(MINUTE, 0, CreatedOnUtcDate),
            0
        ) AS MinuteUtc,
        COUNT(*) AS Hits
    FROM ValidDates
    GROUP BY
        UserAgent,
        DATEADD(
            MINUTE,
            DATEDIFF(MINUTE, 0, CreatedOnUtcDate),
            0
        )
),
PeakMinute AS (
    SELECT
        UserAgent,
        MinuteUtc AS PeakMinuteUtc,
        Hits AS PeakMinuteHits,
        ROW_NUMBER() OVER (
            PARTITION BY UserAgent
            ORDER BY Hits DESC, MinuteUtc ASC
        ) AS rn
    FROM MinuteHits
),
LocalWindow AS (
    SELECT
        p.UserAgent,
        p.PeakMinuteUtc,
        p.PeakMinuteHits,
        m.Hits AS WindowMinuteHits
    FROM PeakMinute p
    JOIN MinuteHits m
        ON m.UserAgent = p.UserAgent
       AND m.MinuteUtc BETWEEN DATEADD(MINUTE, -@WindowMinutes, p.PeakMinuteUtc)
                           AND DATEADD(MINUTE,  @WindowMinutes, p.PeakMinuteUtc)
    WHERE p.rn = 1
),
MedianCalc AS (
    SELECT DISTINCT
        UserAgent,
        PeakMinuteUtc,
        PeakMinuteHits,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY WindowMinuteHits)
            OVER (PARTITION BY UserAgent, PeakMinuteUtc) AS LocalMedianHits
    FROM LocalWindow
)
SELECT
    UserAgent,
    PeakMinuteUtc,
    PeakMinuteHits,
    CAST(LocalMedianHits AS DECIMAL(10,2)) AS LocalMedianHits,
    CAST(
        PeakMinuteHits * 1.0 / NULLIF(LocalMedianHits, 0)
        AS DECIMAL(10,2)
    ) AS BurstScore,
    CASE
        WHEN PeakMinuteHits >= 100
         AND PeakMinuteHits * 1.0 / NULLIF(LocalMedianHits, 0) >= 20
        THEN 1
        ELSE 0
    END AS BurstDetected
FROM MedianCalc
ORDER BY BurstScore DESC, PeakMinuteHits DESC;


