# Zodiac Invoice Management System

A modern invoice processing and management platform with AI-driven error correction capabilities.

## 🚀 Quick Start

### Automated Scripts (Recommended)
1. **Start the system**: Double-click `start_zodiac_system.bat`
2. **Stop the system**: Double-click `stop_zodiac_system.bat`

### Manual Setup

#### Prerequisites
- PostgreSQL Database (running on localhost:5432)
- Python 3.11+ (for backend)
- Node.js 18+ (for frontend)

#### 1. Start Zodiac Backend Server
```bash
cd zodiac-api
pip install -r requirements.txt
python start.py
```

#### 2. Start Zodiac Frontend Server
```bash
cd zodiac-front
npm install
npm run dev
```

## 🌐 Access Points

- **Zodiac Frontend**: http://localhost:3000
- **Zodiac Backend API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs
- **PostgreSQL**: localhost:5432
- **pgAdmin**: http://localhost:8080

## 📁 Project Structure

```
zodiac/
├── zodiac-api/                    # FastAPI Backend
│   ├── app/
│   │   ├── main.py               # Main application
│   │   ├── database.py           # Database configuration
│   │   ├── api/                  # API routes
│   │   ├── models/               # Database models
│   │   └── schemas/              # Pydantic schemas
│   ├── start.py                  # Startup script
│   ├── requirements.txt          # Python dependencies
│   └── .env                      # Environment variables
├── zodiac-front/                 # Next.js Frontend
│   ├── src/
│   │   ├── app/                  # Next.js App Router
│   │   ├── components/           # React components
│   │   ├── contexts/             # React contexts
│   │   ├── lib/                  # Utilities & API client
│   │   └── types/                # TypeScript types
│   └── package.json
├── start_zodiac_system.bat       # Start script
└── stop_zodiac_system.bat       # Stop script
```

## 🔧 Features

### Frontend Features
- ✅ **Authentication**: Sign up and sign in
- ✅ **Dashboard**: Analytics overview with recent activity
- ✅ **Invoice Management**: View and manage uploaded invoices
- ✅ **File Upload**: Drag-and-drop file upload for invoice processing
- ✅ **Error Handling**: Comprehensive error handling with user guidance
- ✅ **Auto-redirect**: Automatic login redirect on session expiry
- ✅ **Responsive Design**: Mobile-friendly interface

### Backend Features
- ✅ **FastAPI**: Modern Python web framework
- ✅ **PostgreSQL**: Relational database with async support
- ✅ **JWT Authentication**: Secure token-based authentication
- ✅ **Invoice Processing**: EDI, XML, X12 file conversion
- ✅ **CORS Support**: Cross-origin resource sharing
- ✅ **API Documentation**: Auto-generated Swagger docs

## 🛠 Development

### Backend Development
```bash
cd zodiac-api
pip install -r requirements.txt
python start.py
```

### Frontend Development
```bash
cd zodiac-front
npm install
npm run dev
```

### Database Management
```bash
# Access pgAdmin (if running)
open http://localhost:8080

# Connect to database
Host: localhost
Port: 5432
Database: mydatabase
Username: myuser
Password: mypassword
```

## 🔍 Debugging

### Frontend Logging
The frontend includes comprehensive logging:
- **API Requests/Responses**: All HTTP calls logged
- **Authentication Flow**: Login/logout tracking
- **File Upload Process**: Upload progress and errors
- **Error Handling**: Detailed error information

### Enable Debug Mode
```javascript
// In browser console
localStorage.setItem('debug', 'true');
```

### Backend Logging
- **Request Logging**: All incoming requests
- **Error Logging**: Detailed error information
- **Database Operations**: Query logging

## 🚨 Troubleshooting

### Common Issues

1. **Backend won't start**
   - Check if PostgreSQL is running: `docker ps`
   - Verify .env file exists and has correct database URL
   - Check if port 8000 is available
   - Install dependencies: `pip install -r requirements.txt`

2. **Frontend won't start**
   - Run `npm install` to install dependencies
   - Check if port 3000 is available
   - Verify Node.js version (18+)

3. **Database connection issues**
   - Ensure PostgreSQL is running on localhost:5432
   - Check database credentials in .env file
   - Verify database exists: `mydatabase`

4. **Authentication errors**
   - Check if backend is running on port 8000
   - Verify CORS settings in backend
   - Clear browser localStorage and try again

### Log Locations
- **Frontend**: Browser console (F12)
- **Backend**: Terminal output
- **Database**: Docker logs

## 📝 API Endpoints

### Authentication
- `POST /auth/login` - User login
- `POST /auth/signup` - User registration
- `GET /auth/me` - Get current user

### Invoice Management
- `GET /api/invoices` - Get all invoices
- `POST /api/invoices` - Create new invoice
- `GET /api/invoices/{id}` - Get invoice by ID
- `PUT /api/invoices/{id}` - Update invoice
- `DELETE /api/invoices/{id}` - Delete invoice

## 🔐 Environment Variables

### Backend (.env)
```env
DATABASE_URL="postgresql+asyncpg://myuser:mypassword@localhost:5432/mydatabase"
DATABASE_POOL_SIZE=10
DATABASE_MAX_OVERFLOW=20
API_HOST=0.0.0.0
API_PORT=8000
API_DEBUG=True
CORS_ORIGINS="http://localhost:3000,http://localhost:3001,http://localhost:5173"
SECRET_KEY="your-secret-key-here-change-in-production"
ALGORITHM="HS256"
```

### Frontend (.env.local)
```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

## 🎯 Next Steps

1. **Test the system**: Sign up, login, upload files
2. **Check logs**: Monitor console for any issues
3. **Verify API**: Test endpoints at http://localhost:8000/docs
4. **Database**: Check data in pgAdmin

## 📞 Support

For issues or questions:
1. Check the troubleshooting section above
2. Review console logs for error details
3. Verify all services are running correctly
4. Check database connectivity

---

**Happy coding! 🚀**
