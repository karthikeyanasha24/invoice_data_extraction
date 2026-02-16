"""
Database Migration for Customer Table V2
Adds tax fields and renames columns
Run this script to migrate the zodiac_customers table
"""
import os
import sys
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    print("ERROR: DATABASE_URL not found in environment variables")
    sys.exit(1)

print("=" * 80)
print("CUSTOMER TABLE V2 MIGRATION")
print("=" * 80)
print(f"Database: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else 'Unknown'}")
print()

# Create engine
engine = create_engine(DATABASE_URL)

migration_steps = [
    {
        "name": "1. Add tax_value column",
        "sql": """
        ALTER TABLE zodiac_customers 
        ADD COLUMN IF NOT EXISTS tax_value NUMERIC(10, 2) DEFAULT 0 NOT NULL;
        """,
        "rollback": "ALTER TABLE zodiac_customers DROP COLUMN IF EXISTS tax_value;"
    },
    {
        "name": "2. Add tax_percentage column",
        "sql": """
        ALTER TABLE zodiac_customers 
        ADD COLUMN IF NOT EXISTS tax_percentage NUMERIC(5, 2) DEFAULT 0 NOT NULL;
        """,
        "rollback": "ALTER TABLE zodiac_customers DROP COLUMN IF EXISTS tax_percentage;"
    },
    {
        "name": "3. Rename format to target_format",
        "sql": """
        DO $$ 
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'zodiac_customers' AND column_name = 'format'
            ) THEN
                ALTER TABLE zodiac_customers RENAME COLUMN format TO target_format;
            END IF;
        END $$;
        """,
        "rollback": "ALTER TABLE zodiac_customers RENAME COLUMN target_format TO format;"
    },
    {
        "name": "4. Rename validation_rules to validation_fields",
        "sql": """
        DO $$ 
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'zodiac_customers' AND column_name = 'validation_rules'
            ) THEN
                ALTER TABLE zodiac_customers RENAME COLUMN validation_rules TO validation_fields;
            END IF;
        END $$;
        """,
        "rollback": "ALTER TABLE zodiac_customers RENAME COLUMN validation_fields TO validation_rules;"
    },
    {
        "name": "5. Update default value for target_format",
        "sql": """
        ALTER TABLE zodiac_customers 
        ALTER COLUMN target_format SET DEFAULT 'xml';
        """,
        "rollback": "ALTER TABLE zodiac_customers ALTER COLUMN target_format SET DEFAULT 'edifact';"
    }
]

def run_migration():
    """Run the migration"""
    print("Starting migration...")
    print()
    
    try:
        with engine.begin() as conn:
            for step in migration_steps:
                print(f"Executing: {step['name']}")
                try:
                    conn.execute(text(step['sql']))
                    print(f"  ✓ Success")
                except Exception as e:
                    print(f"  ✗ Error: {e}")
                    raise
                print()
        
        print("=" * 80)
        print("MIGRATION COMPLETED SUCCESSFULLY!")
        print("=" * 80)
        print()
        print("Summary of changes:")
        print("  • Added tax_value column (NUMERIC(10,2), default 0)")
        print("  • Added tax_percentage column (NUMERIC(5,2), default 0)")
        print("  • Renamed 'format' → 'target_format'")
        print("  • Renamed 'validation_rules' → 'validation_fields'")
        print("  • Updated default value for target_format")
        print()
        
        # Verify migration
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT column_name, data_type, column_default, is_nullable
                FROM information_schema.columns
                WHERE table_name = 'zodiac_customers'
                ORDER BY ordinal_position;
            """))
            
            print("Current table structure:")
            print("-" * 80)
            for row in result:
                print(f"  {row[0]:25} {row[1]:20} Default: {row[2] or 'None':15} Nullable: {row[3]}")
        
        print()
        return True
        
    except Exception as e:
        print()
        print("=" * 80)
        print("MIGRATION FAILED!")
        print("=" * 80)
        print(f"Error: {e}")
        print()
        print("To rollback, run the following SQL commands manually:")
        print()
        for step in reversed(migration_steps):
            print(f"-- {step['name']}")
            print(step['rollback'])
            print()
        return False

def check_existing_customers():
    """Check if there are existing customers that need attention"""
    try:
        with engine.connect() as conn:
            # Check if old column names exist
            result = conn.execute(text("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'zodiac_customers' 
                    AND column_name IN ('format', 'validation_rules')
                );
            """))
            has_old_columns = result.scalar()
            
            # Count existing customers
            result = conn.execute(text("SELECT COUNT(*) FROM zodiac_customers;"))
            customer_count = result.scalar()
            
            print("Pre-migration check:")
            print("-" * 80)
            print(f"  Existing customers: {customer_count}")
            print(f"  Old column names present: {'Yes' if has_old_columns else 'No'}")
            print()
            
            if customer_count > 0 and has_old_columns:
                print("⚠️  WARNING: Existing customers will have tax_value and tax_percentage set to 0")
                print("   You may need to update these values manually after migration.")
                print()
                response = input("Continue with migration? (yes/no): ")
                if response.lower() not in ['yes', 'y']:
                    print("Migration cancelled.")
                    return False
            
            return True
    except Exception as e:
        print(f"Error checking existing data: {e}")
        return False

if __name__ == "__main__":
    print()
    if check_existing_customers():
        success = run_migration()
        sys.exit(0 if success else 1)
    else:
        sys.exit(1)
