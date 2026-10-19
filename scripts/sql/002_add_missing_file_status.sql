-- Allow status = 'missing_file' on dbo.emu_staging (see middleware/routing.py).
--   missing_file : the EMu record has no file_name (no multimedia link), so it can't have a
--                  NetX asset. Routing never looks it up and neither DSS task reads it.
--                  `python -m middleware.requeue --missing-file` puts them back to 'pending'.
--
-- Run once after 001_add_status_column.sql. 001 created status as VARCHAR(10), which is too
-- short for 'missing_file' (12 chars), so this widens it to VARCHAR(20). SQL Server won't alter
-- a column that has a CHECK or DEFAULT on it, so both constraints are dropped and re-added.
-- Idempotent: safe to re-run. Existing values are untouched.

USE EmuStaging;
GO

IF EXISTS (
    SELECT 1 FROM sys.check_constraints
    WHERE name = 'CK_emu_staging_status'
      AND parent_object_id = OBJECT_ID('dbo.emu_staging')
)
    ALTER TABLE dbo.emu_staging DROP CONSTRAINT CK_emu_staging_status;
GO

IF EXISTS (
    SELECT 1 FROM sys.default_constraints
    WHERE name = 'DF_emu_staging_status'
      AND parent_object_id = OBJECT_ID('dbo.emu_staging')
)
    ALTER TABLE dbo.emu_staging DROP CONSTRAINT DF_emu_staging_status;
GO

ALTER TABLE dbo.emu_staging ALTER COLUMN status VARCHAR(20) NOT NULL;
GO

ALTER TABLE dbo.emu_staging
    ADD CONSTRAINT DF_emu_staging_status DEFAULT 'pending' FOR status;
GO

ALTER TABLE dbo.emu_staging WITH CHECK
    ADD CONSTRAINT CK_emu_staging_status
    CHECK (status IN ('pending', 'ready', 'holding', 'missing_file'));
GO
