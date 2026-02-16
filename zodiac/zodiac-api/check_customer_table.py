"""
Script to inspect the zodiac_customers table structure and data
"""
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).parent))

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
from app.models.customer import Customer

# Load environment variables
load_dotenv()

# Get database URL
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    print("❌ DATABASE_URL not found in .env file")
    sys.exit(1)

print("=" * 80)
print("🔍 CUSTOMER TABLE INSPECTOR")
print("=" * 80)
print()

# Create database connection
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
session = Session()

try:
    # 1. Get table structure using SQLAlchemy Inspector
    inspector = inspect(engine)
    
    print("📋 TABLE STRUCTURE: zodiac_customers")
    print("-" * 80)
    
    columns = inspector.get_columns('zodiac_customers')
    print(f"\n{'Column Name':<25} {'Type':<20} {'Nullable':<10} {'Default':<20}")
    print("-" * 80)
    
    for col in columns:
        col_name = col['name']
        col_type = str(col['type'])
        nullable = 'Yes' if col['nullable'] else 'No'
        default = str(col['default']) if col['default'] else '-'
        print(f"{col_name:<25} {col_type:<20} {nullable:<10} {default:<20}")
    
    # 2. Get indexes
    print("\n\n🔑 INDEXES:")
    print("-" * 80)
    indexes = inspector.get_indexes('zodiac_customers')
    for idx in indexes:
        print(f"  • {idx['name']}: {idx['column_names']} (unique: {idx['unique']})")
    
    # 3. Get primary key
    print("\n\n🔐 PRIMARY KEY:")
    print("-" * 80)
    pk = inspector.get_pk_constraint('zodiac_customers')
    print(f"  • {pk['constrained_columns']}")
    
    # 4. Get data count
    print("\n\n📊 DATA SUMMARY:")
    print("-" * 80)
    count = session.query(Customer).count()
    print(f"  Total records: {count}")
    
    # 5. Display all customer data
    print("\n\n📄 CUSTOMER DATA:")
    print("=" * 80)
    
    customers = session.query(Customer).order_by(Customer.id).all()
    
    if not customers:
        print("\n  No customers found in the database.\n")
    else:
        for i, customer in enumerate(customers, 1):
            print(f"\n[{i}] Customer Record:")
            print("-" * 80)
            print(f"  ID:              {customer.id}")
            print(f"  Customer ID:     {customer.customer_id}")
            print(f"  Format:          {customer.format}")
            print(f"  Validation Rules: {customer.validation_rules[:100] if customer.validation_rules else 'None'}{'...' if customer.validation_rules and len(customer.validation_rules) > 100 else ''}")
            print(f"  Created At:      {customer.created_at}")
    
    # 6. Sample query - get unique formats
    print("\n\n📈 STATISTICS:")
    print("-" * 80)
    result = session.execute(text("""
        SELECT format, COUNT(*) as count 
        FROM zodiac_customers 
        GROUP BY format
    """))
    
    print("\nCustomers by format:")
    for row in result:
        print(f"  • {row.format}: {row.count} customer(s)")
    
    print("\n\n✅ Script completed successfully!")
    print("=" * 80)
    
except Exception as e:
    print(f"\n❌ Error occurred: {e}")
    import traceback
    traceback.print_exc()
finally:
    session.close()
