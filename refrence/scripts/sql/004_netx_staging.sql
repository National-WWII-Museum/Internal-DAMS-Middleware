/*
  004_netx_staging.sql
  One row per NetX webhook delivery to POST /api/webhooks/clips
  (api/routers/clips.py). The route inserts the row before answering NetX;
  common/clip_events.py marks it done or failed after processing.

  The mirror of dbo.emu_staging: that table holds EMu records waiting to go
  into NetX, this one holds NetX events waiting to go into EMu.

  Why it exists:
    - event_id is the primary key, so a delivery NetX retries cannot be
      processed twice (the second INSERT fails and the route skips it).
    - A row still 'received' after a service restart is work that was
      accepted but never finished, and can be re-run.

  Only what NetX sent is stored. IRN, checksum and clips are looked up
  fresh from NetX by asset id at processing time, never copied here.

  Idempotent. Run in SSMS as a sysadmin. Touches nothing in dbo.emu_staging.
*/

USE EmuStaging;
GO

SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

IF OBJECT_ID(N'dbo.netx_staging', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.netx_staging (
        -- NetX eventId (a UUID string)
        event_id      VARCHAR(64)    NOT NULL,
        -- which webhook this came from; only 'clips' for now
        event_type    VARCHAR(30)    NOT NULL CONSTRAINT DF_netx_staging_event_type DEFAULT ('clips'),
        -- assetIds exactly as sent, as JSON text: [206839, 206840]
        asset_ids     NVARCHAR(MAX)  NOT NULL,
        -- NetX userId of whoever fired the custom action
        netx_user_id  INT            NULL,

        -- received -> done | failed
        status        VARCHAR(20)    NOT NULL CONSTRAINT DF_netx_staging_status   DEFAULT ('received'),
        error         NVARCHAR(MAX)  NULL,

        received_at   DATETIME2(3)   NOT NULL CONSTRAINT DF_netx_staging_received DEFAULT (SYSUTCDATETIME()),
        processed_at  DATETIME2(3)   NULL,

        CONSTRAINT PK_netx_staging PRIMARY KEY CLUSTERED (event_id ASC),
        CONSTRAINT CK_netx_staging_status
            CHECK (status IN ('received', 'done', 'failed')),
        CONSTRAINT CK_netx_staging_asset_ids
            CHECK (ISJSON(asset_ids) = 1)
    );
END
GO

-- emusync: the API inserts the row, reads it back, and updates status / error /
-- processed_at. No DELETE: rows are a history of what NetX sent.
GRANT SELECT, INSERT, UPDATE ON dbo.netx_staging TO [emusync];
GO

-- Sanity check (run as the admin; impersonates emusync, changes nothing):
EXECUTE AS USER = N'emusync';
    SELECT TOP 1 event_id, event_type, status, received_at FROM dbo.netx_staging;
REVERT;
GO