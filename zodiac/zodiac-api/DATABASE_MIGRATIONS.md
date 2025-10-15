# Database Migration System

This project uses a consolidated database migration system that automatically handles all database setup and migrations during application startup. This approach is ideal for remote server deployment where you want everything to be self-contained.

## Overview

Instead of separate SQL migration files and manual migration scripts, all database initialization and migration logic is consolidated into the application startup process. This ensures that:

- ✅ All migrations run automatically on startup
- ✅ Migrations are idempotent (safe to run multiple times)
- ✅ No manual intervention required
- ✅ Perfect for remote server deployment
- ✅ Easy to maintain and extend

## How It Works

### 1. Automatic Startup Migration

When the FastAPI application starts, it automatically:

1. **Creates database tables** (if they don't exist)
2. **Runs all migrations** to add required columns and indexes
3. **Verifies migration status** and logs results
4. **Continues startup** regardless of migration status

### 2. Migration System

The `DatabaseInitializer` class in `app/database_init.py` handles:

- **Column existence checks** - Only adds columns if they don't exist
- **Index existence checks** - Only creates indexes if they don't exist
- **Error handling** - Graceful handling of migration errors
- **Logging** - Comprehensive logging of all migration steps

### 3. Current Migrations

#### Deleted At Columns (Soft Deletion)
- Adds `deleted_at` column to both invoice tables
- Creates performance indexes for soft deletion queries
- Enables soft delete functionality

#### Processing Steps Error Columns
- Adds `processing_steps_error` JSON column to both invoice tables
- Creates GIN indexes for JSON query performance
- Enables detailed error storage and retrieval

## Usage

### Automatic (Recommended)

Migrations run automatically when you start the application:

```bash
# Start the API server - migrations run automatically
python -m uvicorn app.server:app --host 0.0.0.0 --port 8000
```

### Manual Status Check

You can check the current migration status:

```bash
# Check migration status
python -m app.database_init status
```

### Health Check Endpoint

The `/health` endpoint includes database migration status:

```bash
curl http://localhost:8000/health
```

Response:
```json
{
  "status": "healthy",
  "service": "zodiac-api",
  "database_migrations": {
    "deleted_at_columns": {
      "zodiac_invoice_success_edi": true,
      "zodiac_invoice_failed_edi": true
    },
    "processing_steps_columns": {
      "zodiac_invoice_success_edi": true,
      "zodiac_invoice_failed_edi": true
    },
    "indexes": {
      "deleted_at_indexes": [true, true, true, true],
      "processing_steps_indexes": [true, true]
    }
  }
}
```

## Adding New Migrations

To add a new migration:

1. **Add migration method** to `DatabaseInitializer` class
2. **Call the method** in `run_all_migrations()`
3. **Update status checking** in `get_migration_status()`

Example:

```python
def add_new_feature_columns(self):
    """Add new feature columns"""
    logger.info("Checking for new feature columns...")
    
    migrations = [
        {
            "table": "zodiac_invoice_success_edi",
            "column": "new_feature",
            "sql": "ALTER TABLE zodiac_invoice_success_edi ADD COLUMN IF NOT EXISTS new_feature TEXT NULL;"
        }
    ]
    
    # ... implementation ...
```

## Environment Variables

Required environment variables:

- `DATABASE_URL` - PostgreSQL connection string
- `CORS_ORIGINS` - Allowed CORS origins

## Logging

The migration system provides comprehensive logging:

- ✅ Migration start/completion
- ✅ Column existence checks
- ✅ Index creation status
- ✅ Error handling and recovery
- ✅ Performance metrics

## Benefits

### For Development
- **No manual setup** - Just start the application
- **Consistent environment** - Same setup everywhere
- **Easy testing** - Migrations run in test environments

### For Production
- **Zero downtime** - Migrations are idempotent
- **Automatic recovery** - Handles partial migration failures
- **Monitoring** - Health check includes migration status
- **Remote deployment** - No manual database setup required

## Migration Files (Legacy)

The following files are no longer needed and can be removed:

- `add_processing_steps_columns.sql`
- `add_deleted_at_columns.sql`
- `migrate_add_processing_steps.py`
- `migrate_add_deleted_at.py`

All functionality has been consolidated into `app/database_init.py`.

## Troubleshooting

### Common Issues

1. **Database Connection Error**
   - Check `DATABASE_URL` environment variable
   - Ensure PostgreSQL is running
   - Verify database credentials

2. **Migration Failures**
   - Check application logs for specific errors
   - Verify database permissions
   - Check `/health` endpoint for migration status

3. **Missing Tables**
   - Ensure `Base.metadata.create_all()` runs successfully
   - Check database schema creation

### Debug Mode

Enable debug logging:

```python
import logging
logging.getLogger("app.database_init").setLevel(logging.DEBUG)
```

This will provide detailed information about each migration step.
