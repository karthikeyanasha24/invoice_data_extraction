@echo off
echo Stopping Zodiac Invoice Management System...
echo.

echo Stopping Zodiac Frontend Server...
taskkill /f /im node.exe 2>nul
echo Zodiac Frontend Server stopped
echo.

echo Stopping Zodiac Backend Server...
taskkill /f /im python.exe 2>nul
echo Zodiac Backend Server stopped
echo.

echo All Zodiac servers stopped successfully!
echo.
echo Press any key to exit...
pause > nul
