-- Migration: user_customers, customer_receiver_rfc, is_customer_user
-- For Customer Users and Customer Documents Dashboard.

-- 1. Add is_customer_user to zodiac_users
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'zodiac_users' AND column_name = 'is_customer_user'
    ) THEN
        ALTER TABLE zodiac_users ADD COLUMN is_customer_user BOOLEAN DEFAULT FALSE;
    END IF;
END $$;

-- 2. Create user_customers table
CREATE TABLE IF NOT EXISTS user_customers (
    user_id INTEGER NOT NULL REFERENCES zodiac_users(id) ON DELETE CASCADE,
    customer_id VARCHAR(255) NOT NULL,
    PRIMARY KEY (user_id, customer_id)
);
CREATE INDEX IF NOT EXISTS idx_user_customers_user_id ON user_customers(user_id);
CREATE INDEX IF NOT EXISTS idx_user_customers_customer_id ON user_customers(customer_id);

-- 3. Create customer_receiver_rfc table
CREATE TABLE IF NOT EXISTS customer_receiver_rfc (
    customer_id VARCHAR(255) NOT NULL,
    receiver_rfc VARCHAR(13) NOT NULL,
    PRIMARY KEY (customer_id, receiver_rfc)
);
CREATE INDEX IF NOT EXISTS idx_customer_receiver_rfc_customer_id ON customer_receiver_rfc(customer_id);
CREATE INDEX IF NOT EXISTS idx_customer_receiver_rfc_receiver_rfc ON customer_receiver_rfc(receiver_rfc);
