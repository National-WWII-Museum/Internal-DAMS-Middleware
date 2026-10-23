-- Add tgm to dbo.emu_staging: EMu WebTGM_tab (Thesaurus for Graphic Materials terms),
-- e.g. 'Ordnance--American--United States'. Multi-value, packed by middleware/mapping.py
-- as 'a, b, c'. Synced to the NetX attribute "Thesaurus for Graphic Materials"
-- (see netx-config-files/syncedMetadata.xml).
--
-- Run BEFORE deploying the middleware change - the upsert writes this column and will
-- fail if it doesn't exist. Idempotent: safe to re-run.
-- The emusync login needs no new grant: table-level SELECT/INSERT/UPDATE covers the new column.

USE EmuStaging;
GO

IF COL_LENGTH('dbo.emu_staging', 'tgm') IS NULL
BEGIN
    ALTER TABLE dbo.emu_staging ADD tgm NVARCHAR(MAX) NULL;
END
GO
