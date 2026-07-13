-- Network Analysis - /24 Subnet Evidence
-- Runs across all AdminComment values and detects /24 subnet concentration.

WITH Base AS (
    -- Keep every record for TotalRecords; only normalize /24 for /24-specific metrics.
    SELECT
        AdminComment,
        LTRIM(RTRIM(RangeSubnet24)) AS Subnet24
    FROM Results
    WHERE AdminComment IS NOT NULL
      AND LTRIM(RTRIM(AdminComment)) <> ''
),
Normalized AS (
    -- Exclude only invalid /24 values from /24 calculations.
    SELECT
        AdminComment,
        CASE
            WHEN Subnet24 IS NULL THEN NULL
            WHEN Subnet24 = '' THEN NULL
            WHEN UPPER(Subnet24) IN ('NULL', 'N/A', 'NA', '-', '.') THEN NULL
            ELSE Subnet24
        END AS ValidSubnet24
    FROM Base
),
CandidateTotals AS (
    -- TotalRecords counts all records, even when RangeSubnet24 is missing or invalid.
    SELECT
        AdminComment,
        COUNT(*) AS TotalRecords,
        COUNT(ValidSubnet24) AS RecordsWithSubnet24,
        COUNT(DISTINCT ValidSubnet24) AS UniqueSubnet24
    FROM Normalized
    GROUP BY AdminComment
),
Subnet24Counts AS (
    -- Count valid /24 subnet usage per AdminComment.
    SELECT
        AdminComment,
        ValidSubnet24,
        COUNT(*) AS Subnet24Records
    FROM Normalized
    WHERE ValidSubnet24 IS NOT NULL
    GROUP BY
        AdminComment,
        ValidSubnet24
),
TopSubnet24 AS (
    -- Pick the most common valid /24 subnet for each AdminComment.
    SELECT
        AdminComment,
        ValidSubnet24 AS TopSubnet24,
        Subnet24Records AS TopSubnet24Records,
        ROW_NUMBER() OVER (
            PARTITION BY AdminComment
            ORDER BY Subnet24Records DESC, ValidSubnet24 ASC
        ) AS rn
    FROM Subnet24Counts
),
Final AS (
    -- Calculate concentration percentages and the /24 evidence decision.
    SELECT
        c.AdminComment,
        c.TotalRecords,
        c.RecordsWithSubnet24,
        c.UniqueSubnet24,
        t.TopSubnet24,
        COALESCE(t.TopSubnet24Records, 0) AS TopSubnet24Records,
        CAST(
            COALESCE(t.TopSubnet24Records, 0) * 100.0 / NULLIF(c.TotalRecords, 0)
            AS DECIMAL(10,2)
        ) AS TopSubnet24CoverageFromTotalRecordsPercent,
        CAST(
            COALESCE(t.TopSubnet24Records, 0) * 100.0 / NULLIF(c.RecordsWithSubnet24, 0)
            AS DECIMAL(10,2)
        ) AS TopSubnet24CoverageFromValidSubnet24RecordsPercent,
        CASE
            WHEN c.TotalRecords < 100
             AND c.UniqueSubnet24 < 100
            THEN 'LOW EVIDENCE'

            WHEN COALESCE(t.TopSubnet24Records, 0) * 100.0 / NULLIF(c.RecordsWithSubnet24, 0) >= 20
            THEN 'WORTH CHECKING'

            ELSE 'LOW /24 CONCENTRATION'
        END AS Subnet24EvidenceDecision
    FROM CandidateTotals c
    LEFT JOIN TopSubnet24 t
        ON t.AdminComment = c.AdminComment
       AND t.rn = 1
)
SELECT
    AdminComment,
    TotalRecords,
    RecordsWithSubnet24,
    UniqueSubnet24,
    TopSubnet24,
    TopSubnet24Records,
    TopSubnet24CoverageFromTotalRecordsPercent,
    TopSubnet24CoverageFromValidSubnet24RecordsPercent,
    Subnet24EvidenceDecision
FROM Final
ORDER BY
    CASE
        WHEN Subnet24EvidenceDecision = 'WORTH CHECKING' THEN 1
        WHEN Subnet24EvidenceDecision = 'LOW /24 CONCENTRATION' THEN 2
        WHEN Subnet24EvidenceDecision = 'LOW EVIDENCE' THEN 3
        ELSE 4
    END,
    TopSubnet24CoverageFromValidSubnet24RecordsPercent DESC;
