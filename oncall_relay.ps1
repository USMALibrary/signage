<#
Relays the on-call status file from OneDrive to the data branch.

The "Update On-Call Status" Power Automate flow can no longer write to GitHub
directly (GitHub returns 403 to Microsoft's egress IPs), so the flow writes the
JSON to OneDrive and this script pushes it from the Windows laptop.

All git work goes through feed_git.ps1, which handles stale locks, stuck
rebases, cross-feed mutual exclusion, timeouts and logging.

Setup:
  1. Clone the data branch (or reuse the clone the other feeds push from).
  2. Make sure this script and feed_git.ps1 sit at the clone root.
  3. Schedule every 5 minutes via run-hidden-oncall.vbs, running only when the
     user is logged on, so the OneDrive folder is synced and readable.

Override -SourcePath if the flow writes somewhere other than the default below.
#>
param(
    [string]$RepoPath = $PSScriptRoot,
    [string]$SourcePath = "C:\Users\travis.schaben\OneDrive - West Point\SignageFeeds\on-call.json"
)

. (Join-Path $PSScriptRoot 'feed_git.ps1')

Start-Feed -Name 'oncall' -RepoPath $RepoPath

# Validate before touching git, so a missing or half-written source never commits.
if (-not (Test-Path -LiteralPath $SourcePath)) {
    Exit-Feed -Code 1 -Result 'error' -Detail "source file not found: $SourcePath"
}

$raw = Get-Content -LiteralPath $SourcePath -Raw
try {
    $parsed = $raw | ConvertFrom-Json
} catch {
    Exit-Feed -Code 1 -Result 'error' -Detail "source is not valid JSON: $SourcePath"
}

if ([string]::IsNullOrWhiteSpace($parsed.name) -or [string]::IsNullOrWhiteSpace($parsed.updated)) {
    Exit-Feed -Code 1 -Result 'error' -Detail "source JSON missing name and/or updated: $SourcePath"
}

Invoke-GitOrFail -Arguments @('pull', '--rebase', 'origin', 'data') | Out-Null

Copy-Item -LiteralPath $SourcePath -Destination (Join-Path $RepoPath 'data\on-call.json') -Force

Invoke-GitOrFail -Arguments @('add', 'data/on-call.json') | Out-Null

if ((Invoke-Git -Arguments @('diff', '--cached', '--quiet')).ExitCode -eq 0) {
    Exit-Feed -Code 0 -Result 'nochange'
}

Invoke-GitOrFail -Arguments @('commit', '-m', "Update on-call status $(Get-Date -Format 'yyyy-MM-dd HH:mm')") | Out-Null

Invoke-FeedPush

$hash = (Invoke-Git -Arguments @('rev-parse', '--short', 'HEAD')).Output.Trim()
Exit-Feed -Code 0 -Result 'pushed' -Detail $hash
