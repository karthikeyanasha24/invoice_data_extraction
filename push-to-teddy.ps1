# Commit and push the zodiac tree to branch "teddy" on origin.
# Does not stage zodiac-api/.env or zodiac-api/.venv. Unstages __pycache__ / .pyc if they were added.
#
# Usage:
#   .\push-to-teddy.ps1
#   .\push-to-teddy.ps1 "Your commit message"
#   .\push-to-teddy.bat "Your commit message"

param(
    [Parameter(Position = 0)]
    [string]$Message = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = $PSScriptRoot
Set-Location $RepoRoot

if (-not (Test-Path (Join-Path $RepoRoot ".git"))) {
    Write-Error "No .git found in $RepoRoot. Run this script from the repo root (new_1)."
}

$branch = (git rev-parse --abbrev-ref HEAD).Trim()
if ($branch -ne "teddy") {
    Write-Host "Checking out teddy (was: $branch)..."
    git checkout teddy
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

# Stage everything under zodiac except API secrets and local venv
git add -- "zodiac" ":(exclude)zodiac/zodiac-api/.env" ":(exclude)zodiac/zodiac-api/.venv"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# If .env or .venv were already tracked, drop them from this commit
git reset HEAD -- "zodiac/zodiac-api/.env" 2>$null
git reset HEAD -- "zodiac/zodiac-api/.venv" 2>$null

$staged = git diff --cached --name-only
foreach ($path in $staged) {
    if ($path -match '__pycache__|\.pyc$') {
        git reset HEAD -- $path
    }
}

if (git diff --cached --quiet) {
    Write-Host "Nothing staged to commit (no changes under zodiac, or only excluded paths). `n`n git status:"
    git status -sb
    exit 0
}

if (-not $Message) {
    $Message = "teddy: update $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
}

git commit -m $Message
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

git push origin teddy
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Pushed to origin/teddy."
