-- Global IP Analysis
-- Shows total records and distinct User-Agents per IP across all Results.

WITH Base AS (
    SELECT
        LTRIM(RTRIM(
            CASE
                WHEN IPAddress IS NULL THEN NULL
                WHEN CHARINDEX(',', IPAddress) > 0
                THEN LEFT(IPAddress, CHARINDEX(',', IPAddress) - 1)
                ELSE IPAddress
            END
        )) AS IPAddress,
        AdminComment
    FROM Results
)
SELECT
    IPAddress,
    COUNT(*) AS RecordCount,
    COUNT(DISTINCT AdminComment) AS DistinctAdminComments
FROM Base
WHERE IPAddress IS NOT NULL
GROUP BY IPAddress
ORDER BY RecordCount DESC;
