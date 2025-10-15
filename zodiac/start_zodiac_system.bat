@echo off
echo Starting Zodiac Invoice Management System...
echo.

echo Starting Zodiac Backend Server...
cd /d "%~dp0zodiac-api"
echo Installing dependencies if needed...
pip install -r requirements.txt >nul 2>&1
start "Zodiac Backend Server" cmd /k "uvicorn app.main:app --host 0.0.0.0 --port 8000"
echo Zodiac Backend Server starting...
echo.

echo Starting Zodiac Frontend Server...
cd /d "%~dp0zodiac-front"
start "Zodiac Frontend Server" cmd /k "npm run dev"
echo Zodiac Frontend Server starting...
echo.

echo All Zodiac servers are starting up!
echo.
echo Zodiac Backend API: http://localhost:8000
echo Zodiac Frontend: http://localhost:3000
echo.
echo Press any key to exit...
pause > nul
