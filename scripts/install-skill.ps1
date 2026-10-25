<#
.SYNOPSIS
  Installs the sprint-review-progress skill for Claude Code (copies it to ~/.claude/skills).
.DESCRIPTION
  Also copies this repo's .env to ~/.sprint-review.env when that file does not exist yet,
  so the installed skill can find its Jira settings from any folder.
.EXAMPLE
  ./scripts/install-skill.ps1
  ./scripts/install-skill.ps1 -Force   # overwrite an existing install
#>
param([switch]$Force)

$ErrorActionPreference = 'Stop'
$repo   = Split-Path -Parent $PSScriptRoot
$source = Join-Path $repo 'skills/sprint-review-progress'
$target = Join-Path $HOME '.claude/skills/sprint-review-progress'

if ((Test-Path $target) -and -not $Force) {
    Write-Host "Already installed at $target. Run with -Force to overwrite." -ForegroundColor Yellow
    exit 1
}
New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
if (Test-Path $target) { Remove-Item -Recurse -Force $target }
Copy-Item -Recurse $source $target
Write-Host "Skill installed: $target" -ForegroundColor Green

$envSrc = Join-Path $repo '.env'
$envDst = Join-Path $HOME '.sprint-review.env'
if ((Test-Path $envSrc) -and -not (Test-Path $envDst)) {
    Copy-Item $envSrc $envDst
    Write-Host "Settings copied to $envDst" -ForegroundColor Green
} elseif (-not (Test-Path $envDst)) {
    Write-Host "No settings yet. Copy .env.example to $envDst and fill it in." -ForegroundColor Yellow
}
Write-Host "Check it:  python `"$target/scripts/sprint_progress.py`" --check"
