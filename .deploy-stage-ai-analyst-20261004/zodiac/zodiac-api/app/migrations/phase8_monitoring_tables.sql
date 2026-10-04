-- Phase 8: Pipeline monitoring tables — expand-only
-- Safe to run multiple times where IF NOT EXISTS allows.

CREATE TABLE IF NOT EXISTS pipeline_timelines (
    id SERIAL PRIMARY KEY,
    correlation_id VARCHAR(64) NOT NULL UNIQUE,
    customer_id VARCHAR(255) NOT NULL
        REFERENCES zodiac_customers(customer_id) ON DELETE CASCADE,
    country_code VARCHAR(64) NULL,
    adapter_name VARCHAR(128) NULL,
    document_type VARCHAR(64) NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'RUNNING',
    current_stage VARCHAR(64) NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    latency_ms DOUBLE PRECISION NULL,
    failure_reason TEXT NULL,
    failed_stage VARCHAR(64) NULL,
    government_reference VARCHAR(255) NULL,
    erp_reference VARCHAR(255) NULL,
    started_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITHOUT TIME ZONE NULL,
    extra JSON NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE NULL
);

CREATE INDEX IF NOT EXISTS ix_pipeline_timelines_correlation_id
    ON pipeline_timelines (correlation_id);
CREATE INDEX IF NOT EXISTS ix_pipeline_timelines_customer_id
    ON pipeline_timelines (customer_id);
CREATE INDEX IF NOT EXISTS ix_pipeline_timelines_customer_status
    ON pipeline_timelines (customer_id, status);
CREATE INDEX IF NOT EXISTS ix_pipeline_timelines_customer_started
    ON pipeline_timelines (customer_id, started_at);

CREATE TABLE IF NOT EXISTS pipeline_events (
    id SERIAL PRIMARY KEY,
    correlation_id VARCHAR(64) NOT NULL,
    customer_id VARCHAR(255) NOT NULL
        REFERENCES zodiac_customers(customer_id) ON DELETE CASCADE,
    country_code VARCHAR(64) NULL,
    stage VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    message TEXT NULL,
    duration_ms DOUBLE PRECISION NULL,
    attempt INTEGER NOT NULL DEFAULT 1,
    error_code VARCHAR(64) NULL,
    payload JSON NULL,
    occurred_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_pipeline_events_correlation_id
    ON pipeline_events (correlation_id);
CREATE INDEX IF NOT EXISTS ix_pipeline_events_customer_id
    ON pipeline_events (customer_id);
CREATE INDEX IF NOT EXISTS ix_pipeline_events_corr_stage
    ON pipeline_events (correlation_id, stage);
CREATE INDEX IF NOT EXISTS ix_pipeline_events_customer_at
    ON pipeline_events (customer_id, occurred_at);

CREATE TABLE IF NOT EXISTS pipeline_metrics (
    id SERIAL PRIMARY KEY,
    customer_id VARCHAR(255) NOT NULL
        REFERENCES zodiac_customers(customer_id) ON DELETE CASCADE,
    correlation_id VARCHAR(64) NULL,
    name VARCHAR(128) NOT NULL,
    value DOUBLE PRECISION NOT NULL DEFAULT 0,
    unit VARCHAR(32) NULL,
    tags JSON NULL,
    recorded_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_pipeline_metrics_customer_id
    ON pipeline_metrics (customer_id);
CREATE INDEX IF NOT EXISTS ix_pipeline_metrics_correlation_id
    ON pipeline_metrics (correlation_id);
CREATE INDEX IF NOT EXISTS ix_pipeline_metrics_customer_name_at
    ON pipeline_metrics (customer_id, name, recorded_at);

CREATE TABLE IF NOT EXISTS alert_history (
    id SERIAL PRIMARY KEY,
    customer_id VARCHAR(255) NOT NULL
        REFERENCES zodiac_customers(customer_id) ON DELETE CASCADE,
    correlation_id VARCHAR(64) NULL,
    alert_type VARCHAR(64) NOT NULL,
    severity VARCHAR(32) NOT NULL DEFAULT 'warning',
    title VARCHAR(255) NOT NULL,
    message TEXT NULL,
    channel VARCHAR(64) NOT NULL DEFAULT 'log',
    delivered BOOLEAN NOT NULL DEFAULT FALSE,
    payload JSON NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_alert_history_customer_id
    ON alert_history (customer_id);
CREATE INDEX IF NOT EXISTS ix_alert_history_correlation_id
    ON alert_history (correlation_id);
CREATE INDEX IF NOT EXISTS ix_alert_history_customer_type
    ON alert_history (customer_id, alert_type);
