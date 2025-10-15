# Database Migration: Add Soft Deletion Support

This migration adds `deleted_at` columns to the invoice tables to enable soft deletion functionality.

## What This Migration Does

- Adds `deleted_at TIMESTAMP WITH TIME ZONE NULL` column to both:
  - `zodiac_invoice_success_edi` table
  - `zodiac_invoice_failed_edi` table
- Creates performance indexes for soft deletion queries
- Enables the recycle bin functionality in the frontend

## How to Run the Migration

### Option 1: Using Python Script (Recommended)

```bash
cd zodiac/zodiac-api
python migrate_add_deleted_at.py
```

The script will:
- Connect to your database using `DATABASE_URL` environment variable
- Run the migration safely with `IF NOT EXISTS` clauses
- Verify the columns were added successfully
- Show you the results

### Option 2: Using SQL Script Directly

```bash
# Connect to your PostgreSQL database
psql -d your_database_name -U your_username

# Run the SQL script
\i add_deleted_at_columns.sql
```

### Option 3: Manual SQL Commands

```sql
-- Add deleted_at columns
ALTER TABLE zodiac_invoice_success_edi 
ADD COLUMN deleted_at TIMESTAMP WITH TIME ZONE NULL;

ALTER TABLE zodiac_invoice_failed_edi 
ADD COLUMN deleted_at TIMESTAMP WITH TIME ZONE NULL;

-- Add indexes for performance
CREATE INDEX idx_zodiac_invoice_success_edi_deleted_at ON zodiac_invoice_success_edi(deleted_at);
CREATE INDEX idx_zodiac_invoice_failed_edi_deleted_at ON zodiac_invoice_failed_edi(deleted_at);
CREATE INDEX idx_zodiac_invoice_success_edi_user_deleted ON zodiac_invoice_success_edi(user_id, deleted_at);
CREATE INDEX idx_zodiac_invoice_failed_edi_user_deleted ON zodiac_invoice_failed_edi(user_id, deleted_at);
```

## Environment Setup

Make sure your `DATABASE_URL` environment variable is set:

```bash
export DATABASE_URL="postgresql://username:password@localhost:5432/zodiac_db"
```

Or create a `.env` file in the `zodiac-api` directory:

```
DATABASE_URL=postgresql://username:password@localhost:5432/zodiac_db
```

## Verification

After running the migration, you can verify it worked by checking the columns:

```sql
SELECT table_name, column_name, data_type, is_nullable 
FROM information_schema.columns 
WHERE table_name IN ('zodiac_invoice_success_edi', 'zodiac_invoice_failed_edi') 
AND column_name = 'deleted_at';
```

You should see 2 rows returned with the `deleted_at` columns.

## What Happens After Migration

Once the migration is complete:

1. **Soft Deletion Works**: Deleting invoices will set `deleted_at` timestamp instead of removing records
2. **Recycle Bin Functions**: Users can view deleted invoices and restore them
3. **API Endpoints Work**: `/api/v1/invoices/deleted` endpoint will return deleted invoices
4. **Frontend Integration**: The recycle bin functionality in the UI will work properly

## Rollback (If Needed)

If you need to rollback this migration:

```sql
-- Remove indexes first
DROP INDEX IF EXISTS idx_zodiac_invoice_success_edi_user_deleted;
DROP INDEX IF EXISTS idx_zodiac_invoice_failed_edi_user_deleted;
DROP INDEX IF EXISTS idx_zodiac_invoice_success_edi_deleted_at;
DROP INDEX IF EXISTS idx_zodiac_invoice_failed_edi_deleted_at;

-- Remove columns
ALTER TABLE zodiac_invoice_success_edi DROP COLUMN IF EXISTS deleted_at;
ALTER TABLE zodiac_invoice_failed_edi DROP COLUMN IF EXISTS deleted_at;
```

## Troubleshooting

### Error: "column does not exist"
- Make sure you're running the migration against the correct database
- Check that the table names match your actual schema

### Error: "permission denied"
- Ensure your database user has ALTER TABLE permissions
- You may need to run as a database superuser

### Error: "relation does not exist"
- Verify the table names in your database match the expected names
- Check that the tables were created properly

## Support

If you encounter issues with this migration, check:
1. Database connection string is correct
2. User has sufficient permissions
3. Tables exist with expected names
4. No conflicting migrations are running

