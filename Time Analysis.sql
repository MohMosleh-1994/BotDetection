-- Time Analysis / Burst Evidence
-- Runs across all CleanAdminComment values and returns one decision per value.

DECLARE @WindowMinutes INT = 5;

WITH Base AS (
    SELECT
        CleanAdminComment,
        TRY_CONVERT(datetime2, CreatedOnUtc) AS CreatedOnUtcDate
    FROM Results
    WHERE CleanAdminComment IS NOT NULL
      AND LTRIM(RTRIM(CleanAdminComment)) <> ''
),
CandidateTotals AS (
    SELECT
        CleanAdminComment,
        COUNT(*) AS TotalRecords,
        SUM(
            CASE
                WHEN CreatedOnUtcDate IS NOT NULL THEN 1
                ELSE 0
            END
        ) AS RecordsWithValidDate
    FROM Base
    GROUP BY CleanAdminComment
),
ValidDates AS (
    SELECT
        CleanAdminComment,
        CreatedOnUtcDate
    FROM Base
    WHERE CreatedOnUtcDate IS NOT NULL
),
MinuteHits AS (
    SELECT
        CleanAdminComment,
        DATEADD(
            MINUTE,
            DATEDIFF(MINUTE, 0, CreatedOnUtcDate),
            0
        ) AS MinuteUtc,
        COUNT(*) AS Hits
    FROM ValidDates
    GROUP BY
        CleanAdminComment,
        DATEADD(
            MINUTE,
            DATEDIFF(MINUTE, 0, CreatedOnUtcDate),
            0
        )
),
PeakMinute AS (
    SELECT
        CleanAdminComment,
        MinuteUtc AS PeakMinuteUtc,
        Hits AS PeakMinuteHits,
        ROW_NUMBER() OVER (
            PARTITION BY CleanAdminComment
            ORDER BY Hits DESC, MinuteUtc ASC
        ) AS rn
    FROM MinuteHits
),
LocalWindow AS (
    SELECT
        p.CleanAdminComment,
        p.PeakMinuteUtc,
        p.PeakMinuteHits,
        m.Hits AS WindowMinuteHits
    FROM PeakMinute p
    JOIN MinuteHits m
        ON m.CleanAdminComment = p.CleanAdminComment
       AND m.MinuteUtc BETWEEN DATEADD(MINUTE, -@WindowMinutes, p.PeakMinuteUtc)
                           AND DATEADD(MINUTE,  @WindowMinutes, p.PeakMinuteUtc)
    WHERE p.rn = 1
),
MedianCalc AS (
    SELECT DISTINCT
        CleanAdminComment,
        PeakMinuteUtc,
        PeakMinuteHits,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY WindowMinuteHits)
            OVER (PARTITION BY CleanAdminComment, PeakMinuteUtc) AS LocalMedianHits
    FROM LocalWindow
)
SELECT
    t.CleanAdminComment,
    t.TotalRecords,
    t.RecordsWithValidDate,
    m.PeakMinuteUtc,
    m.PeakMinuteHits,
    CAST(m.LocalMedianHits AS DECIMAL(10,2)) AS LocalMedianHits,
    CAST(
        m.PeakMinuteHits * 1.0 / NULLIF(m.LocalMedianHits, 0)
        AS DECIMAL(10,2)
    ) AS BurstScore,
    CASE
        WHEN t.TotalRecords < 100 THEN 'LOW EVIDENCE'
        WHEN t.RecordsWithValidDate = 0 THEN 'NO VALID DATES'
        WHEN m.PeakMinuteHits >= 100
         AND m.PeakMinuteHits * 1.0 / NULLIF(m.LocalMedianHits, 0) >= 20
        THEN 'WORTH CHECKING'
        ELSE 'LOW BURST'
    END AS TimeEvidenceDecision
FROM CandidateTotals t
LEFT JOIN MedianCalc m
    ON m.CleanAdminComment = t.CleanAdminComment
ORDER BY
    CASE
        WHEN t.TotalRecords >= 100
         AND m.PeakMinuteHits >= 100
         AND m.PeakMinuteHits * 1.0 / NULLIF(m.LocalMedianHits, 0) >= 20
        THEN 0
        WHEN t.TotalRecords < 100 THEN 2
        ELSE 1
    END,
    BurstScore DESC,
    m.PeakMinuteHits DESC,
    t.TotalRecords DESC;
