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
)
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
    ) AS BurstScore,
    CASE
        WHEN t.TotalRecords < 100 THEN 'LOW EVIDENCE'
        WHEN t.RecordsWithValidDate = 0 THEN 'NO VALID DATES'
        WHEN m.PeakMinuteHits * 1.0 / NULLIF(m.LocalMedianHits, 0) >= 20
        THEN 'WORTH CHECKING'
        WHEN m.PeakMinuteHits >= 100
          OR m.PeakMinuteHits * 1.0 / NULLIF(m.LocalMedianHits, 0) >= 10
        THEN 'MODERATE BURST'
        ELSE 'LOW BURST'
    END AS TimeEvidenceDecision
FROM CandidateTotals t
LEFT JOIN MedianCalc m
    ON m.AdminComment = t.AdminComment
ORDER BY
    CASE
        WHEN t.TotalRecords < 100 THEN 4
        WHEN t.RecordsWithValidDate = 0 THEN 5
        WHEN m.PeakMinuteHits * 1.0 / NULLIF(m.LocalMedianHits, 0) >= 20
        THEN 1
        WHEN m.PeakMinuteHits >= 100
          OR m.PeakMinuteHits * 1.0 / NULLIF(m.LocalMedianHits, 0) >= 10
        THEN 2
        ELSE 3
    END,
    BurstScore DESC,
    m.PeakMinuteHits DESC,
    t.TotalRecords DESC;
