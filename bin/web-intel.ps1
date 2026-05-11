#!/usr/bin/env pwsh
# web-intel wrapper for Windows (PowerShell 7+)
# Usage: & "$SKILL_DIR/bin/web-intel.ps1" search "query"
$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SkillDir = Split-Path -Parent $ScriptDir

# Find a working python (prefer 3.11-3.13 over 3.14+ for dep compat)
function Find-Python {
    foreach ($v in @('python3.13', 'python3.12', 'python3.11', 'python3', 'python')) {
        $p = Get-Command $v -ErrorAction SilentlyContinue
        if ($p) { return $p.Source }
    }
    Write-Error "ERROR: python not found. Install Python 3.11+"
    exit 1
}

$Python = Find-Python
& $Python "$SkillDir\scripts\web.py" @args
exit $LASTEXITCODE
