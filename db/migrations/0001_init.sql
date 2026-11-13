-- Initial schema for Intelligent Video Intelligence.
--
-- This mirrors the SQLAlchemy models in app/services/db.py exactly. In normal
-- operation `init_db()` (SQLAlchemy `Base.metadata.create_all`) creates these
-- tables automatically on first run -- this file exists so the schema can
-- also be reviewed, diffed, and applied explicitly in a production PostgreSQL
-- deployment (e.g. via `psql`, Flyway, or any migration runner), per the
-- brief's requirement for an explicit database schema/migration.
--
-- Apply with:
--   psql "$DATABASE_URL" -f db/migrations/0001_init.sql
--
-- Safe to run against a fresh database. Not idempotent against a database
-- already initialized by SQLAlchemy with a different column order -- in that
-- case this file is for review only; let init_db() own table creation.

BEGIN;

CREATE TABLE IF NOT EXISTS cameras (
    camera_id   VARCHAR(128) PRIMARY KEY,
    name        VARCHAR(256) NOT NULL DEFAULT '',
    "group"     VARCHAR(128) NOT NULL DEFAULT 'default',
    source      VARCHAR(512) NOT NULL DEFAULT '',
    status      VARCHAR(32)  NOT NULL DEFAULT 'unknown',   -- online | offline | reconnecting | stopped
    last_seen   TIMESTAMP NULL,
    last_error  TEXT NULL
);

CREATE TABLE IF NOT EXISTS observations (
    id              SERIAL PRIMARY KEY,
    camera_id       VARCHAR(128) NOT NULL,
    track_id        VARCHAR(128) NOT NULL,
    entity_type     VARCHAR(128) NOT NULL,                  -- raw detector label, e.g. "person"
    category        VARCHAR(32)  NOT NULL DEFAULT 'unknown', -- human | animal | vehicle | other | unknown
    confidence      REAL NOT NULL,
    "timestamp"     TIMESTAMP NOT NULL,
    bbox_json       TEXT NOT NULL DEFAULT '[]',
    analysis_json   TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_observations_camera_id   ON observations (camera_id);
CREATE INDEX IF NOT EXISTS ix_observations_track_id     ON observations (track_id);
CREATE INDEX IF NOT EXISTS ix_observations_entity_type  ON observations (entity_type);
CREATE INDEX IF NOT EXISTS ix_observations_category     ON observations (category);
CREATE INDEX IF NOT EXISTS ix_observations_timestamp    ON observations ("timestamp");

CREATE TABLE IF NOT EXISTS incidents (
    id                          SERIAL PRIMARY KEY,
    camera_id                   VARCHAR(128) NOT NULL,
    incident_type               VARCHAR(64) NOT NULL,   -- accident | violence_fight | robbery_intrusion |
                                                         -- dangerous_activity | crowd_anomaly | vehicle_incident |
                                                         -- other_configured
    confidence                  REAL NOT NULL,
    "timestamp"                 TIMESTAMP NOT NULL,
    track_ids                   TEXT NOT NULL DEFAULT '[]',
    reasoning                   TEXT NOT NULL DEFAULT '[]',
    metadata_json                TEXT NOT NULL DEFAULT '{}',
    evidence_path                TEXT NULL,
    verified                     INTEGER NOT NULL DEFAULT 0,
    cross_camera_links_json      TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS ix_incidents_camera_id      ON incidents (camera_id);
CREATE INDEX IF NOT EXISTS ix_incidents_incident_type  ON incidents (incident_type);
CREATE INDEX IF NOT EXISTS ix_incidents_timestamp      ON incidents ("timestamp");

CREATE TABLE IF NOT EXISTS audit_log (
    id              SERIAL PRIMARY KEY,
    "timestamp"     TIMESTAMP NOT NULL,
    actor           VARCHAR(128) NOT NULL DEFAULT 'system',
    action          VARCHAR(128) NOT NULL,
    target_type     VARCHAR(64) NOT NULL DEFAULT '',
    target_id       VARCHAR(128) NOT NULL DEFAULT '',
    details_json    TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_audit_log_timestamp  ON audit_log ("timestamp");
CREATE INDEX IF NOT EXISTS ix_audit_log_action     ON audit_log (action);

COMMIT;
