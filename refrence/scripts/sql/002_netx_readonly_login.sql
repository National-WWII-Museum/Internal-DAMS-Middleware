/*
  002_netx_readonly_login.sql
  Creates a read-only SQL login for scripts that read the NetX database
  directly (e.g. scripts/test_clips.py reading video clip times from
  dbo.constituent). Run in SSMS as a sysadmin on the SQL Server instance
  that hosts the NetX database.

  Scope is deliberately narrow: SELECT on two tables, nothing else.
  Nothing here touches EmuStaging or the emusync login.

  1. Replace <CHANGE_ME> with a strong password (and put the same value in
     .env as NETX_DB_PASSWORD).
  2. Run the whole script.
*/

USE [master];
GO

IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'netx_readonly')
BEGIN
    CREATE LOGIN [netx_readonly]
        WITH PASSWORD = N'<CHANGE_ME>',
             CHECK_POLICY = ON,
             CHECK_EXPIRATION = OFF,          -- service account: no forced expiry
             DEFAULT_DATABASE = [NetX];
END
GO

USE [NetX];
GO

IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'netx_readonly')
    CREATE USER [netx_readonly] FOR LOGIN [netx_readonly];
GO

GRANT SELECT ON OBJECT::dbo.constituent TO [netx_readonly];   -- clips / keyframes
GRANT SELECT ON OBJECT::dbo.image       TO [netx_readonly];   -- asset id -> filename
GO

-- Need another table later (e.g. asset_attr_value)? Add a GRANT SELECT line
-- for just that table. Do not add the user to db_datareader.

-- Sanity check (run as the admin; impersonates the new user, changes nothing):
EXECUTE AS USER = N'netx_readonly';
    SELECT TOP 1 constituent_id, image_id, type, start_time, end_time FROM dbo.constituent;
    SELECT TOP 1 image_id, name FROM dbo.image;
REVERT;
GO
