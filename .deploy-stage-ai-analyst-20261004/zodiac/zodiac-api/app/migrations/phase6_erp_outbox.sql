-- Phase 6: ERP push outbox (idempotency) — expand-only
-- Safe to run multiple times where IF NOT EXISTS allows.

CREATE TABLE IF NOT EXISTS erp_push_outbox (
    id SERIAL PRIMARY KEY,
    idempotency_key VARCHAR(128) NOT NULL,
    customer_id VARCHAR(255) NOT NULL
        REFERENCES zodiac_customers(customer_id) ON DELETE CASCADE,
    correlation_id VARCHAR(64) NOT NULL,
    connection_key VARCHAR(64) NOT NULL DEFAULT 'primary',
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    request_hash VARCHAR(128) NULL,
    response_body TEXT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE NULL,
    CONSTRAINT uq_erp_push_outbox_idempotency_key UNIQUE (idempotency_key)
);

CREATE INDEX IF NOT EXISTS ix_erp_push_outbox_idempotency_key
    ON erp_push_outbox (idempotency_key);
CREATE INDEX IF NOT EXISTS ix_erp_push_outbox_customer_id
    ON erp_push_outbox (customer_id);
CREATE INDEX IF NOT EXISTS ix_erp_push_outbox_correlation_id
    ON erp_push_outbox (correlation_id);
CREATE INDEX IF NOT EXISTS ix_erp_push_outbox_status
    ON erp_push_outbox (status);
