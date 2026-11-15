-- Routing status for dbo.emu_staging (see middleware/routing.py).
--   pending : staged / re-staged by polling, not routed yet. Neither DSS task reads it.
--   ready   : NetX already has an asset with this IRN -> EMuByFilename DSS task syncs it.
--   holding : NetX has no asset with this IRN yet -> EMuHolding DSS task keeps retrying;
--             routing.py promotes it to 'ready' once the IRN appears in NetX.
--   missing_file : no file_name on the row (see 002_add_missing_file_status.sql).
--
-- Idempotent. Existing rows become 'pending' and are routed on the next
-- `python -m middleware.routing` run.
-- The emusync login needs no new grant for the status column (table-level SELECT/UPDATE
-- covers it), but the view below DOES need its own SELECT grant - see the end of this file.

USE EmuStaging;
GO

IF COL_LENGTH('dbo.emu_staging', 'status') IS NULL
BEGIN
    ALTER TABLE dbo.emu_staging
        ADD status VARCHAR(20) NOT NULL
            CONSTRAINT DF_emu_staging_status DEFAULT 'pending'
            CONSTRAINT CK_emu_staging_status CHECK (status IN ('pending', 'ready', 'holding', 'missing_file'));
END
GO

-- Manual-fix queue: records NetX doesn't have an IRN for yet, oldest first.
-- (The other dev's web app can read this view directly.)
CREATE OR ALTER VIEW dbo.v_emu_holding AS
SELECT irn, title, file_name, accession_number, first_seen_at, updated_at
FROM dbo.emu_staging
WHERE status = 'holding';
GO

-- A table-level grant does not cover a view: without this the web app's /holding.csv
-- fails with SQL error 229 (shown to the browser as "database unavailable").
GRANT SELECT ON dbo.v_emu_holding TO emusync;
GO
