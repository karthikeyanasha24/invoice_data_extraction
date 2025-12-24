#!/usr/bin/env python3
"""
Database migration script to add invoice_business_data table for business intelligence.
This table stores extracted business data for analytics and reporting.
"""

import sys
import os
from sqlalchemy import text

# Add the app directory to the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import engine

def run_migration():
    """Run the database migration to add business intelligence table"""
    
    print("Zodiac Database Migration: Add Business Intelligence Table")
    print("=" * 70)
    
    try:
        # Test connection
        with engine.connect() as conn:
            print("✅ Database connection successful")
            
            # Migration SQL
            migration_sql = """
            -- Create invoice_business_data table for business intelligence
            CREATE TABLE IF NOT EXISTS invoice_business_data (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                
                -- Link to invoices
                success_invoice_id INTEGER REFERENCES zodiac_invoice_success_edi(id),
                failed_invoice_id INTEGER REFERENCES zodiac_invoice_failed_edi(id),
                tracking_id UUID NOT NULL,
                user_id INTEGER REFERENCES zodiac_users(id) NOT NULL,
                
                -- Customer data
                customer_id VARCHAR(255),
                customer_name VARCHAR(500),
                customer_country VARCHAR(10),
                customer_city VARCHAR(255),
                customer_address TEXT,
                customer_tax_id VARCHAR(100),
                
                -- Supplier data
                supplier_id VARCHAR(255),
                supplier_name VARCHAR(500),
                supplier_country VARCHAR(10),
                
                -- Product data (JSONB for flexible structure)
                products JSONB,
                product_count INTEGER DEFAULT 0,
                
                -- Industry classification
                industry VARCHAR(100),
                industry_confidence VARCHAR(20) DEFAULT 'medium',
                industry_keywords_matched JSONB,
                
                -- Financial data
                invoice_number VARCHAR(100),
                invoice_date TIMESTAMP,
                due_date TIMESTAMP,
                total_amount DECIMAL(15, 2),
                tax_amount DECIMAL(15, 2),
                currency VARCHAR(10) DEFAULT 'USD',
                
                -- E2E Lifecycle tracking
                current_stage VARCHAR(50) NOT NULL,
                stage_status VARCHAR(20) NOT NULL,
                failed_at_stage VARCHAR(50),
                failure_reason TEXT,
                lifecycle_stages JSONB,
                
                -- Metadata
                source_format VARCHAR(20),
                target_format VARCHAR(20),
                request_type VARCHAR(20) DEFAULT 'web',
                
                -- Timestamps
                created_at TIMESTAMP DEFAULT NOW() NOT NULL,
                updated_at TIMESTAMP
            );
            
            -- Create indexes for performance
            CREATE INDEX IF NOT EXISTS idx_invoice_business_data_tracking_id 
                ON invoice_business_data(tracking_id);
            
            CREATE INDEX IF NOT EXISTS idx_invoice_business_data_user_id 
                ON invoice_business_data(user_id);
            
            CREATE INDEX IF NOT EXISTS idx_invoice_business_data_success_invoice 
                ON invoice_business_data(success_invoice_id);
            
            CREATE INDEX IF NOT EXISTS idx_invoice_business_data_failed_invoice 
                ON invoice_business_data(failed_invoice_id);
            
            CREATE INDEX IF NOT EXISTS idx_invoice_business_data_customer_id 
                ON invoice_business_data(customer_id);
            
            CREATE INDEX IF NOT EXISTS idx_invoice_business_data_customer_name 
                ON invoice_business_data(customer_name);
            
            CREATE INDEX IF NOT EXISTS idx_invoice_business_data_customer_country 
                ON invoice_business_data(customer_country);
            
            CREATE INDEX IF NOT EXISTS idx_invoice_business_data_industry 
                ON invoice_business_data(industry);
            
            CREATE INDEX IF NOT EXISTS idx_invoice_business_data_supplier_id 
                ON invoice_business_data(supplier_id);
            
            CREATE INDEX IF NOT EXISTS idx_invoice_business_data_current_stage 
                ON invoice_business_data(current_stage);
            
            CREATE INDEX IF NOT EXISTS idx_invoice_business_data_stage_status 
                ON invoice_business_data(stage_status);
            
            CREATE INDEX IF NOT EXISTS idx_invoice_business_data_failed_at_stage 
                ON invoice_business_data(failed_at_stage);
            
            CREATE INDEX IF NOT EXISTS idx_invoice_business_data_created_at 
                ON invoice_business_data(created_at);
            
            -- Composite indexes for common queries
            CREATE INDEX IF NOT EXISTS idx_customer_analysis 
                ON invoice_business_data(user_id, customer_id, created_at);
            
            CREATE INDEX IF NOT EXISTS idx_country_analysis 
                ON invoice_business_data(user_id, customer_country, created_at);
            
            CREATE INDEX IF NOT EXISTS idx_industry_analysis 
                ON invoice_business_data(user_id, industry, created_at);
            
            CREATE INDEX IF NOT EXISTS idx_lifecycle_tracking 
                ON invoice_business_data(user_id, current_stage, stage_status);
            
            CREATE INDEX IF NOT EXISTS idx_supplier_analysis 
                ON invoice_business_data(user_id, supplier_id, created_at);
            """
            
            print("🔄 Running migration...")
            
            # Execute migration
            conn.execute(text(migration_sql))
            conn.commit()
            
            print("✅ Migration SQL executed successfully!")
            
            # Verify the table was created
            verification_sql = """
            SELECT table_name, column_name, data_type
            FROM information_schema.columns 
            WHERE table_name = 'invoice_business_data'
            ORDER BY ordinal_position;
            """
            
            result = conn.execute(text(verification_sql))
            columns = result.fetchall()
            
            print(f"\n📊 Verification - Created table with {len(columns)} columns:")
            for row in columns[:10]:  # Show first 10 columns
                print(f"  • {row[1]} ({row[2]})")
            
            if len(columns) > 10:
                print(f"  ... and {len(columns) - 10} more columns")
            
            # Verify indexes
            index_verification_sql = """
            SELECT indexname 
            FROM pg_indexes 
            WHERE tablename = 'invoice_business_data'
            ORDER BY indexname;
            """
            
            result = conn.execute(text(index_verification_sql))
            indexes = result.fetchall()
            
            print(f"\n🔍 Created {len(indexes)} indexes:")
            for idx in indexes[:5]:
                print(f"  • {idx[0]}")
            if len(indexes) > 5:
                print(f"  ... and {len(indexes) - 5} more indexes")
            
            if len(columns) >= 30:
                print("\n✅ Migration completed successfully! Business intelligence table is ready.")
                print("\n📈 Next steps:")
                print("  1. Integrate BI extraction into invoice processing")
                print("  2. Create dashboard API endpoints")
                print("  3. Build frontend Business tab")
            else:
                print(f"\n⚠️ Expected ~30 columns, found {len(columns)}. Please check the migration.")
                
    except Exception as e:
        print(f"\n❌ Migration error: {e}")
        print("\nIf the table already exists, this is expected. Otherwise, check your database connection.")
        sys.exit(1)

if __name__ == "__main__":
    run_migration()

