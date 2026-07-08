EXEC sp_rename 'Results.column1', 'CustomerId', 'COLUMN';
EXEC sp_rename 'Results.column2', 'StoreId', 'COLUMN';
EXEC sp_rename 'Results.column3', 'RangeSubnet24', 'COLUMN';
EXEC sp_rename 'Results.column4', 'RangeSubnet16', 'COLUMN';
EXEC sp_rename 'Results.column5', 'IPAddress', 'COLUMN';
EXEC sp_rename 'Results.column6', 'ASN', 'COLUMN';
EXEC sp_rename 'Results.column7', 'CreatedOnUtc', 'COLUMN';
EXEC sp_rename 'Results.column8', 'AdminComment', 'COLUMN';
EXEC sp_rename 'Results.column9', 'CleanAdminComment', 'COLUMN';
EXEC sp_rename 'Results.column10', 'CheckIPLink', 'COLUMN';

