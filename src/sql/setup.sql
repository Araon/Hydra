CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create the table
CREATE TABLE IF NOT EXISTS tasks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    command VARCHAR NOT NULL,
    job_type VARCHAR NOT NULL DEFAULT 'legacy_command',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    scheduled_at TIMESTAMP NOT NULL,
    picked_at TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    failed_at TIMESTAMP,
    status VARCHAR NOT NULL DEFAULT 'queued',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    lease_expires_at TIMESTAMP,
    assigned_worker_id VARCHAR
);

-- Upgrade an existing v1 data directory without dropping scheduled tasks.
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS job_type VARCHAR NOT NULL DEFAULT 'legacy_command';
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS payload JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS status VARCHAR NOT NULL DEFAULT 'queued';
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS max_attempts INTEGER NOT NULL DEFAULT 3;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMP;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS assigned_worker_id VARCHAR;

-- Create an index on scheduled_at
CREATE INDEX idx_scheduled_at ON tasks (scheduled_at);
CREATE INDEX IF NOT EXISTS idx_tasks_dispatch ON tasks (status, scheduled_at);
