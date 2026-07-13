-- Global /24 Subnet Analysis
-- Shows total records and distinct User-Agents per /24 subnet across all Results.

SELECT
    RangeSubnet24,
    COUNT(*) AS RecordCount,
    COUNT(DISTINCT AdminComment) AS DistinctAdminComments
FROM Results
WHERE RangeSubnet24 IS NOT NULL
GROUP BY RangeSubnet24
ORDER BY RecordCount DESC;
