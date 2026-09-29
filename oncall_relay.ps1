<#
Relays the on-call status file from OneDrive to the data branch.

The "Update On-Call Status" Power Automate flow can no longer write to GitHub
directly (GitHub returns 403 to Microsoft's egress IPs), so the flow writes the
JSON to OneDrive and this script pushes it from the Windows laptop.

Setup:
  1. Clone the data branch (or reuse the clone the other feeds push from):
       git clone -b data https://github.com/USMALibrary/signage.git C:\signage-data
  2. Make sure this script sits at the clone root.
  3. Schedule it every 5 minutes via run-hidden-oncall.vbs, running only when
     the user is logged on, so the OneDrive folder is synced and readable.

Override -SourcePath if the flow writes somewhere other than the default below.
#>
param(
    [string]$RepoPath = $PSScriptRoot,
    [string]$SourcePath = "C:\Users\travis.schaben\OneDrive - West Point\SignageFeeds\on-call.json"
)

# Validate before touching git, so a missing or malformed source never commits.
if (-not (Test-Path -LiteralPath $SourcePath)) {
    Write-Error "Source file not found: $SourcePath"
    exit 1
}

$raw = Get-Content -LiteralPath $SourcePath -Raw
try {
    $parsed = $raw | ConvertFrom-Json
} catch {
    Write-Error "Source file is not valid JSON: $SourcePath"
    exit 1
}

if ([string]::IsNullOrWhiteSpace($parsed.name) -or [string]::IsNullOrWhiteSpace($parsed.updated)) {
    Write-Error "Source JSON is missing name and/or updated: $SourcePath"
    exit 1
}

Set-Location $RepoPath

git pull --rebase origin data

Copy-Item -LiteralPath $SourcePath -Destination (Join-Path $RepoPath "data\on-call.json") -Force

git add data/on-call.json
git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Output "No changes to commit"
    exit 0
}

git commit -m "Update on-call status $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
git push origin data
if ($LASTEXITCODE -ne 0) {
    Write-Output "Push failed, retrying after rebase..."
    git pull --rebase origin data
    git push origin data
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Push failed after rebase"
        exit 1
    }
}
