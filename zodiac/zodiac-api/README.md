# Zodiac API

A RESTful API for invoice data extraction built with FastAPI and PostgreSQL.

## Features

- FastAPI framework for high-performance API
- PostgreSQL database integration with SQLAlchemy ORM
- CORS middleware for frontend integration
- Environment-based configuration
- Invoice management with items support
- Automatic API documentation
- Clean modular structure with organized app package

## Project Structure

```
zodiac-api/
├── app/                    # Main application package
│   ├── __init__.py        # Package initialization
│   ├── main.py            # FastAPI application
│   ├── database.py        # Database configuration
│   ├── api/               # API routes
│   │   └── invoices.py    # Invoice endpoints
│   ├── models/            # Database models
│   │   ├── __init__.py    # Model imports
│   │   └── invoice.py     # Invoice models
│   └── schemas/           # Pydantic schemas
│       └── invoice.py     # Invoice schemas
├── start.py               # Startup script
├── test_api.py           # API testing script
├── .env                   # Environment variables
├── requirements.txt      # Dependencies
├── pyproject.toml       # UV project config
└── README.md             # Documentation
```

## Setup

1. **Install dependencies:**
   ```bash
   uv sync
   ```

2. **Configure environment:**
   - Copy `.env` file and update database credentials
   - Set your PostgreSQL connection string
   - Configure CORS origins for your frontend

3. **Run the API:**
   ```bash
   uv run python start.py
   ```

   Or with uvicorn directly:
   ```bash
   uv run uvicorn app.server:app --reload --host 0.0.0.0 --port 8000
   ```

## API Endpoints

### Health Check
- `GET /` - Root endpoint
- `GET /health` - Health check

### Invoices
- `GET /api/v1/invoices/` - List all invoices
- `GET /api/v1/invoices/{id}` - Get specific invoice
- `POST /api/v1/invoices/` - Create new invoice
- `PUT /api/v1/invoices/{id}` - Update invoice
- `DELETE /api/v1/invoices/{id}` - Delete invoice
- `GET /api/v1/invoices/{id}/items` - Get invoice items
- `POST /api/v1/invoices/{id}/items` - Add item to invoice

## API Documentation

Once the server is running, visit:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Database Schema

### Invoices Table
- `id` - Primary key
- `invoice_number` - Unique invoice identifier
- `vendor_name` - Vendor/supplier name
- `invoice_date` - Date of invoice
- `due_date` - Payment due date
- `total_amount` - Total invoice amount
- `currency` - Currency code (default: USD)
- `status` - Invoice status (default: pending)
- `raw_text` - Original extracted text
- `extracted_data` - Processed data (JSON)
- `is_processed` - Processing status flag
- `created_at` - Creation timestamp
- `updated_at` - Last update timestamp

### Invoice Items Table
- `id` - Primary key
- `invoice_id` - Foreign key to invoices
- `description` - Item description
- `quantity` - Item quantity
- `unit_price` - Price per unit
- `line_total` - Total for this line item
- `created_at` - Creation timestamp

## Environment Variables

- `DATABASE_URL` - PostgreSQL connection string
- `API_HOST` - API host (default: 0.0.0.0)
- `API_PORT` - API port (default: 8000)
- `API_DEBUG` - Debug mode (default: True)
- `CORS_ORIGINS` - Comma-separated list of allowed origins
- `SECRET_KEY` - Secret key for security

## Development

The API is configured for development with:
- Auto-reload on code changes
- CORS enabled for local frontend development
- Detailed error messages
- Interactive API documentation
