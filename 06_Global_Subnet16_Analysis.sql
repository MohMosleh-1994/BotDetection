-- Global /16 Subnet Analysis
-- Shows total records and distinct User-Agents per /16 subnet across all Results.

SELECT
    RangeSubnet16,
    COUNT(*) AS RecordCount,
    COUNT(DISTINCT AdminComment) AS DistinctAdminComments
FROM Results
WHERE RangeSubnet16 IS NOT NULL
GROUP BY RangeSubnet16
ORDER BY RecordCount DESC;
