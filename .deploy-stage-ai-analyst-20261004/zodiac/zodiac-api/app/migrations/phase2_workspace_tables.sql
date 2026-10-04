-- Phase 2 (hardened): Customer Workspace tables — expand-only
-- Supports: N customers, N ERP connections/customer, N adapters/customer
-- Safe to run multiple times where IF NOT EXISTS / DO blocks allow.

-- 1) Settings (1:1 customer)
CREATE TABLE IF NOT EXISTS workspace_settings (
    id SERIAL PRIMARY KEY,
    customer_id VARCHAR(255) NOT NULL UNIQUE
        REFERENCES zodiac_customers(customer_id) ON DELETE CASCADE,
    display_name VARCHAR(255) NULL,
    pipeline_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    ai_scoped BOOLEAN NOT NULL DEFAULT TRUE,
    monitoring_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    flags JSON NULL,
    notes TEXT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE NULL,
    created_by INTEGER NULL
);

CREATE INDEX IF NOT EXISTS ix_workspace_settings_customer_id
    ON workspace_settings (customer_id);

-- Add monitoring_enabled if table already existed from earlier Phase 2 draft
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'workspace_settings' AND column_name = 'monitoring_enabled'
    ) THEN
        ALTER TABLE workspace_settings
            ADD COLUMN monitoring_enabled BOOLEAN NOT NULL DEFAULT TRUE;
    END IF;
END $$;

-- 2) ERP connections (N per customer via connection_key)
CREATE TABLE IF NOT EXISTS workspace_erp_connections (
    id SERIAL PRIMARY KEY,
    customer_id VARCHAR(255) NOT NULL
        REFERENCES zodiac_customers(customer_id) ON DELETE CASCADE,
    connection_key VARCHAR(64) NOT NULL DEFAULT 'primary',
    label VARCHAR(255) NULL,
    base_url VARCHAR(1024) NULL,
    callback_url VARCHAR(1024) NULL,
    auth_type VARCHAR(64) NOT NULL DEFAULT 'none',
    client_id_ref VARCHAR(512) NULL,
    client_secret_ref VARCHAR(512) NULL,
    extra_config JSON NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE NULL,
    CONSTRAINT uq_workspace_erp_customer_key UNIQUE (customer_id, connection_key)
);

CREATE INDEX IF NOT EXISTS ix_workspace_erp_connections_customer_id
    ON workspace_erp_connections (customer_id);
CREATE INDEX IF NOT EXISTS ix_workspace_erp_connections_connection_key
    ON workspace_erp_connections (connection_key);

-- Migrate earlier draft uniqueness (customer_id only) → (customer_id, connection_key)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'workspace_erp_connections'
          AND constraint_name = 'uq_workspace_erp_customer'
    ) THEN
        ALTER TABLE workspace_erp_connections DROP CONSTRAINT uq_workspace_erp_customer;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'workspace_erp_connections' AND column_name = 'connection_key'
    ) THEN
        ALTER TABLE workspace_erp_connections
            ADD COLUMN connection_key VARCHAR(64) NOT NULL DEFAULT 'primary';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'workspace_erp_connections' AND column_name = 'label'
    ) THEN
        ALTER TABLE workspace_erp_connections ADD COLUMN label VARCHAR(255) NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'workspace_erp_connections'
          AND constraint_name = 'uq_workspace_erp_customer_key'
    ) THEN
        ALTER TABLE workspace_erp_connections
            ADD CONSTRAINT uq_workspace_erp_customer_key UNIQUE (customer_id, connection_key);
    END IF;
END $$;

-- 3) Adapter config (N countries per customer)
CREATE TABLE IF NOT EXISTS workspace_adapter_config (
    id SERIAL PRIMARY KEY,
    customer_id VARCHAR(255) NOT NULL
        REFERENCES zodiac_customers(customer_id) ON DELETE CASCADE,
    country_code VARCHAR(32) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    endpoint_url_ref VARCHAR(512) NULL,
    auth_type VARCHAR(64) NULL,
    auth_secret_ref VARCHAR(512) NULL,
    document_types JSON NULL,
    rules_version VARCHAR(64) NULL,
    mapping_ref VARCHAR(512) NULL,
    extra_config JSON NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE NULL,
    CONSTRAINT uq_workspace_adapter_country UNIQUE (customer_id, country_code)
);

CREATE INDEX IF NOT EXISTS ix_workspace_adapter_config_customer_id
    ON workspace_adapter_config (customer_id);
CREATE INDEX IF NOT EXISTS ix_workspace_adapter_config_country_code
    ON workspace_adapter_config (country_code);
CREATE INDEX IF NOT EXISTS ix_workspace_adapter_config_enabled
    ON workspace_adapter_config (customer_id, enabled);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'workspace_adapter_config' AND column_name = 'auth_type'
    ) THEN
        ALTER TABLE workspace_adapter_config ADD COLUMN auth_type VARCHAR(64) NULL;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'workspace_adapter_config' AND column_name = 'auth_secret_ref'
    ) THEN
        ALTER TABLE workspace_adapter_config ADD COLUMN auth_secret_ref VARCHAR(512) NULL;
    END IF;
END $$;

-- ROLLBACK (manual, only if required — does not affect production invoice/SAT tables):
-- DROP TABLE IF EXISTS workspace_adapter_config;
-- DROP TABLE IF EXISTS workspace_erp_connections;
-- DROP TABLE IF EXISTS workspace_settings;
