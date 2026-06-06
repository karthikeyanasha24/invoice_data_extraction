@echo off
cd /d "%~dp0"

set BRANCH=ak-updates-%DATE:~-4%%DATE:~3,2%%DATE:~0,2%

echo ============================================================
echo  Creating and pushing branch: %BRANCH%
echo ============================================================

:: Create new branch
git checkout -b %BRANCH%
if %errorlevel% neq 0 (
    echo ERROR: Could not create branch. Trying to switch to it...
    git checkout %BRANCH%
)

:: Stage everything
echo.
echo Staging all changes...
git add -A

:: Commit
echo.
echo Committing...
git commit -m "AK updates: DB schema extractor, AI query tool, API push test - %DATE%"

:: Push
echo.
echo Pushing to origin/%BRANCH%...
git push -u origin %BRANCH%

echo.
echo ============================================================
if %errorlevel% equ 0 (
    echo  SUCCESS - Branch pushed to GitHub
    echo  https://github.com/dodandre/invoice_data_extraction/tree/%BRANCH%
) else (
    echo  Push failed - check your GitHub credentials
)
echo ============================================================
pause
