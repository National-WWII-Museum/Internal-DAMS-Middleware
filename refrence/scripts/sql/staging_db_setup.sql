-- staging_db_setup.sql
-- Recreates the EmuStaging database from scratch: the database, both tables, their
-- constraints, the holding view, the database users and their permissions.
-- One file for everything; it replaces the old incremental scripts (001-003), which
-- are kept only for history.
--
-- Safe to re-run: every object is created only if it is missing, and existing tables
-- and data are never altered or dropped. It does NOT upgrade an older copy of the
-- database. Use it to build a new one, or to repair a missing piece such as a grant.
--
-- Source: the tables, view and constraints were scripted from the live database with
-- SSMS Generate Scripts on 2026-11-07. The GRANTs were NOT part of that output; they
-- are worked out from the code (see the notes on each). Check them against the live
-- database with the query at the bottom before relying on them.
--
-- Run it in SSMS as a sysadmin (or a login that can create databases).
--
-- BEFORE running: the SQL logins must already exist. They are server-level and carry
-- passwords, so they are not created here. Rebuilding on the same server: they already
-- exist. On a new server, create them first with real passwords:
--     CREATE LOGIN [emusync] WITH PASSWORD = N'<strong password>';
--     CREATE LOGIN [emuview] WITH PASSWORD = N'<strong password>';  -- optional, see below
-- emusync is the login used by the middleware, the web app and the NetX DSS tasks
-- (.env and netx-config-files/syncedMetadata.xml); use the same password in both places.
--
-- No data is restored. emu_staging refills from the polling job; with an empty
-- sync_state the watermark falls back to DEFAULT_SYNC_DATE in middleware/state.py,
-- so the first poll re-stages everything modified since that date.
--
-- To try it without touching the real database, find/replace EmuStaging with
-- EmuStaging_test (it appears in the DB_ID / CREATE DATABASE / USE lines below, in the
-- collation comment, and in the USE after the database is created).

USE master;
GO

-- Uses the server default collation. The live database's collation was not in the
-- scripted output; check it with:
--   SELECT collation_name FROM sys.databases WHERE name = 'EmuStaging';
IF DB_ID(N'EmuStaging') IS NULL
    CREATE DATABASE EmuStaging;
GO

USE EmuStaging;
GO

---------------------------------------------------------------------------------------
-- 1. Database users (each needs its server login to exist already)
---------------------------------------------------------------------------------------
IF DATABASE_PRINCIPAL_ID(N'emusync') IS NULL
    CREATE USER [emusync] FOR LOGIN [emusync] WITH DEFAULT_SCHEMA = [dbo];
GO

-- emuview exists on the live database but nothing in this repo references it. It is
-- assumed to be a read-only login for viewing the data. Skipped if the login is absent.
IF SUSER_ID(N'emuview') IS NOT NULL AND DATABASE_PRINCIPAL_ID(N'emuview') IS NULL
    CREATE USER [emuview] FOR LOGIN [emuview] WITH DEFAULT_SCHEMA = [dbo];
GO

---------------------------------------------------------------------------------------
-- 2. dbo.emu_staging - the landing table (one row per EMu record, keyed on irn)
---------------------------------------------------------------------------------------
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

IF OBJECT_ID(N'dbo.emu_staging', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.emu_staging (
        -- key and sync bookkeeping (managed by the database / DSS callbacks)
        irn                     NVARCHAR(100)  NOT NULL,
        synced                  BIT            NOT NULL CONSTRAINT DF_emu_staging_synced      DEFAULT (0),
        sync_failed             BIT            NOT NULL CONSTRAINT DF_emu_staging_sync_failed DEFAULT (0),
        synced_at               DATETIME2(3)   NULL,
        first_seen_at           DATETIME2(3)   NOT NULL CONSTRAINT DF_emu_staging_first_seen  DEFAULT (SYSUTCDATETIME()),
        updated_at              DATETIME2(3)   NOT NULL CONSTRAINT DF_emu_staging_updated_at  DEFAULT (SYSUTCDATETIME()),

        -- columns written by the middleware (middleware/mapping.py WRITE_COLUMNS)
        date_modified           DATE           NULL,
        time_modified           NVARCHAR(20)   NULL,
        modified_at             DATETIME2(3)   NULL,
        record_type             NVARCHAR(100)  NULL,
        title                   NVARCHAR(1000) NULL,
        accession_number        NVARCHAR(200)  NULL,
        credit_line             NVARCHAR(1000) NULL,
        collection_description  NVARCHAR(MAX)  NULL,
        donor_name              NVARCHAR(510)  NULL,
        hometown                NVARCHAR(510)  NULL,
        video_length            NVARCHAR(100)  NULL,
        latitude                NVARCHAR(100)  NULL,
        longitude               NVARCHAR(100)  NULL,
        units                   NVARCHAR(MAX)  NULL,
        geography               NVARCHAR(MAX)  NULL,
        topical_subjects        NVARCHAR(MAX)  NULL,
        object_types            NVARCHAR(MAX)  NULL,
        organizations           NVARCHAR(MAX)  NULL,
        theaters                NVARCHAR(MAX)  NULL,
        branches                NVARCHAR(MAX)  NULL,
        local_terms             NVARCHAR(MAX)  NULL,
        battle_events           NVARCHAR(MAX)  NULL,
        brief_summary           NVARCHAR(MAX)  NULL,
        interview_summary       NVARCHAR(MAX)  NULL,
        summary_data            NVARCHAR(MAX)  NULL,
        formats                 NVARCHAR(MAX)  NULL,
        interview_date          NVARCHAR(50)   NULL,
        geo_hierarchy           NVARCHAR(MAX)  NULL,

        -- reserved: no EMu source yet (except collection_title, which the middleware
        -- does write)
        alternate_title         NVARCHAR(1000) NULL,
        collection_title        NVARCHAR(1000) NULL,
        person                  NVARCHAR(1000) NULL,
        honorees                NVARCHAR(1000) NULL,
        powkia                  NVARCHAR(200)  NULL,
        getty_geo_id            NVARCHAR(200)  NULL,
        asset_url               NVARCHAR(2000) NULL,
        asset_type              NVARCHAR(510)  NULL,

        raw_json                NVARCHAR(MAX)  NULL,
        file_name               NVARCHAR(500)  NULL,

        -- routing status (middleware/routing.py): pending -> ready | holding
        -- 'missing_file' is no longer set by anything but is still allowed here, to
        -- match the live database.
        status                  VARCHAR(20)    NOT NULL CONSTRAINT DF_emu_staging_status DEFAULT ('pending'),

        tgm                     NVARCHAR(MAX)  NULL,

        CONSTRAINT PK_emu_staging PRIMARY KEY CLUSTERED (irn ASC),
        CONSTRAINT CK_emu_staging_status
            CHECK (status IN ('pending', 'ready', 'holding', 'missing_file'))
    );
END
GO

---------------------------------------------------------------------------------------
-- 3. dbo.sync_state - append-only run log; the newest row holds the poll watermark
---------------------------------------------------------------------------------------
IF OBJECT_ID(N'dbo.sync_state', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.sync_state (
        id              INT           NOT NULL CONSTRAINT DF_sync_state_id DEFAULT (1),
        last_sync_date  DATETIME2(7)  NULL,
        last_run_at     DATETIME2(7)  NULL,
        rows_processed  INT           NULL,
        -- NOTE: 500 on the live database, but middleware/state.py truncates notes to
        -- 1000 and polling.py writes the full exception text on failure, so a long
        -- error message can fail to save. Widen this column or truncate to 500 in code.
        notes           NVARCHAR(500) NULL,
        CONSTRAINT PK_sync_state PRIMARY KEY CLUSTERED (id ASC)
    );
END
GO

---------------------------------------------------------------------------------------
-- 4. dbo.v_emu_holding - records NetX has no IRN for yet (CSV download on the web app)
---------------------------------------------------------------------------------------
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

CREATE OR ALTER VIEW dbo.v_emu_holding AS
SELECT irn, title, file_name, accession_number, first_seen_at, updated_at
FROM dbo.emu_staging
WHERE status = 'holding';
GO

---------------------------------------------------------------------------------------
-- 5. Permissions
--    A table-level grant does not cover a view, so the view needs its own.
---------------------------------------------------------------------------------------

-- emusync: used by the middleware (polling MERGE into emu_staging, routing status
-- updates, sync_state log), the web app (list, CSV, delete selected rows) and the NetX
-- DSS tasks (read rows, update synced / sync_failed / status, delete finished rows).
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.emu_staging   TO [emusync];
GRANT SELECT, INSERT                 ON dbo.sync_state    TO [emusync];
GRANT SELECT                         ON dbo.v_emu_holding TO [emusync];
GO

-- emuview: ASSUMED read-only. Adjust after checking the live permissions (below).
IF DATABASE_PRINCIPAL_ID(N'emuview') IS NOT NULL
BEGIN
    GRANT SELECT ON dbo.emu_staging   TO [emuview];
    GRANT SELECT ON dbo.v_emu_holding TO [emuview];
END
GO

---------------------------------------------------------------------------------------
-- Check what the live database actually grants (run separately, compare with section 5)
---------------------------------------------------------------------------------------
-- SELECT pr.name AS grantee, pe.permission_name, pe.state_desc,
--        COALESCE(OBJECT_NAME(pe.major_id), 'DATABASE') AS on_object
-- FROM sys.database_permissions pe
-- JOIN sys.database_principals pr ON pr.principal_id = pe.grantee_principal_id
-- WHERE pr.name NOT IN ('public', 'dbo')
-- ORDER BY pr.name, on_object, pe.permission_name;
--
-- SELECT r.name AS role_name, m.name AS member
-- FROM sys.database_role_members rm
-- JOIN sys.database_principals r ON r.principal_id = rm.role_principal_id
-- JOIN sys.database_principals m ON m.principal_id = rm.member_principal_id
-- WHERE m.name IN ('emusync', 'emuview');
