@echo off
REM Andy-only deploy to EXISTING zodiac-back (never zodiac-api-nu)
cd /d C:\Users\hp\Downloads\INVOICE_DATA_EXTRACTION_22_08\invoice_data_extraction\zodiac\zodiac-api
git pull
echo === .vercel\project.json (must be zodiac-back) ===
type .vercel\project.json
echo.
echo If projectName is not zodiac-back: STOP and relink. Do NOT create a new project.
echo.
pause
echo Deploying to production...
npx vercel --prod
echo.
echo After deploy, prove 31f0fef/ab79e24+ routing:
echo   Compare 2004 and 2005 by month.  -^> monthly_trend
echo   Which month had the biggest margin decline? -^> monthly_trend
pause
