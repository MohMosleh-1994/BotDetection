-- Time Analysis / Burst Evidence
-- Runs across all AdminComment values and returns one decision per value.

DECLARE @WindowMinutes INT = 5;

WITH Base AS (
    SELECT
        AdminComment,
        TRY_CONVERT(datetime2, CreatedOnUtc) AS CreatedOnUtcDate
    FROM Results
    WHERE AdminComment IS NOT NULL
      AND LTRIM(RTRIM(AdminComment)) <> ''
),
CandidateTotals AS (
    SELECT
        AdminComment,
        COUNT(*) AS TotalRecords,
        SUM(
            CASE
                WHEN CreatedOnUtcDate IS NOT NULL THEN 1
                ELSE 0
            END
        ) AS RecordsWithValidDate
    FROM Base
    GROUP BY AdminComment
),
ValidDates AS (
    SELECT
        AdminComment,
        CreatedOnUtcDate
    FROM Base
    WHERE CreatedOnUtcDate IS NOT NULL
),
MinuteHits AS (
    SELECT
        AdminComment,
        DATEADD(
            MINUTE,
            DATEDIFF(MINUTE, 0, CreatedOnUtcDate),
            0
        ) AS MinuteUtc,
        COUNT(*) AS Hits
    FROM ValidDates
    GROUP BY
        AdminComment,
        DATEADD(
            MINUTE,
            DATEDIFF(MINUTE, 0, CreatedOnUtcDate),
            0
        )
),
PeakMinute AS (
    SELECT
        AdminComment,
        MinuteUtc AS PeakMinuteUtc,
        Hits AS PeakMinuteHits,
        ROW_NUMBER() OVER (
            PARTITION BY AdminComment
            ORDER BY Hits DESC, MinuteUtc ASC
        ) AS rn
    FROM MinuteHits
),
LocalWindow AS (
    SELECT
        p.AdminComment,
        p.PeakMinuteUtc,
        p.PeakMinuteHits,
        m.Hits AS WindowMinuteHits
    FROM PeakMinute p
    JOIN MinuteHits m
        ON m.AdminComment = p.AdminComment
       AND m.MinuteUtc BETWEEN DATEADD(MINUTE, -@WindowMinutes, p.PeakMinuteUtc)
                           AND DATEADD(MINUTE,  @WindowMinutes, p.PeakMinuteUtc)
    WHERE p.rn = 1
),
MedianCalc AS (
    SELECT DISTINCT
        AdminComment,
        PeakMinuteUtc,
        PeakMinuteHits,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY WindowMinuteHits)
            OVER (PARTITION BY AdminComment, PeakMinuteUtc) AS LocalMedianHits
    FROM LocalWindow
),
Metrics AS (
    -- Preserve the existing peak, local median, and burst calculations.
    SELECT
        t.AdminComment,
        t.TotalRecords,
        t.RecordsWithValidDate,
        m.PeakMinuteUtc,
        m.PeakMinuteHits,
        CAST(m.LocalMedianHits AS DECIMAL(10,2)) AS LocalMedianHits,
        CAST(
            m.PeakMinuteHits * 1.0 / NULLIF(m.LocalMedianHits, 0)
            AS DECIMAL(10,2)
        ) AS BurstScore
    FROM CandidateTotals t
    LEFT JOIN MedianCalc m
        ON m.AdminComment = t.AdminComment
),
ComponentScores AS (
    SELECT
        *,
        CASE
            WHEN COALESCE(PeakMinuteHits, 0) < 50 THEN 0
            WHEN PeakMinuteHits < 75 THEN 2
            WHEN PeakMinuteHits < 100 THEN 4
            WHEN PeakMinuteHits < 150 THEN 7
            ELSE 10
        END AS PeakVolumeScore,
        CASE
            WHEN COALESCE(BurstScore, 0) < 2 THEN 0
            WHEN BurstScore < 5 THEN 1
            WHEN BurstScore < 10 THEN 2
            WHEN BurstScore < 20 THEN 3
            WHEN BurstScore < 40 THEN 4
            ELSE 5
        END AS BurstScoreValue
    FROM Metrics
),
Scored AS (
    SELECT
        *,
        PeakVolumeScore + BurstScoreValue AS TimeScore
    FROM ComponentScores
)
SELECT
    AdminComment,
    TotalRecords,
    RecordsWithValidDate,
    PeakMinuteUtc,
    PeakMinuteHits,
    LocalMedianHits,
    BurstScore,
    PeakVolumeScore,
    BurstScoreValue,
    TimeScore,
    CASE
        WHEN TimeScore >= 13 THEN 'VERY HIGH'
        WHEN TimeScore >= 10 THEN 'HIGH'
        WHEN TimeScore >= 7 THEN 'MEDIUM'
        WHEN TimeScore >= 4 THEN 'LOW'
        ELSE 'VERY LOW'
    END AS TimePriority
FROM Scored
ORDER BY
    TimeScore DESC,
    PeakMinuteHits DESC,
    BurstScore DESC,
    TotalRecords DESC;
