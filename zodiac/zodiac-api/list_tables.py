"""
Script to list all tables in the database
"""
import os
from dotenv import load_dotenv
import psycopg2
from urllib.parse import urlparse

# Load environment variables
load_dotenv()

def list_tables():
    """Connect to database and list all tables"""
    database_url = os.getenv("DATABASE_URL")
    
    if not database_url:
        print("ERROR: DATABASE_URL not found in .env file")
        return
    
    try:
        # Parse the database URL
        result = urlparse(database_url)
        
        # Connect to the database
        conn = psycopg2.connect(
            host=result.hostname,
            port=result.port or 5432,
            user=result.username,
            password=result.password,
            database=result.path[1:],  # Remove leading '/'
            sslmode='require' if 'sslmode=require' in database_url else None
        )
        
        cursor = conn.cursor()
        
        # Query to get all tables from public schema
        query = """
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            ORDER BY table_name;
        """
        
        cursor.execute(query)
        tables = cursor.fetchall()
        
        print(f"\nFound {len(tables)} table(s) in the database:\n")
        print("-" * 50)
        for table in tables:
            print(table[0])
        print("-" * 50)
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    list_tables()
