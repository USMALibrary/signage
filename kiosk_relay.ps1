<#
Relays Help Desk kiosk request data from OneDrive to the data branch.

The "Kiosk Request" Power Automate side cannot write to GitHub (403 from
Microsoft egress IPs), so a flow dumps the HelpDeskKioskRequests list to
OneDrive and this script summarizes it and pushes data/kiosk-requests.json.

PRIVACY: the repo is public. The raw OneDrive file may contain patron names;
this script emits ONLY counts plus time / request type / status. Never add
requester names or free-text fields to the output.

Raw file (written by the flow, JSON array):
  [ { "created": "2026-11-10T15:32:00Z", "type": "Help printing", "status": "Completed" }, ... ]
Map in the flow's Select: created = the request-time column, type = RequestType,
status = Status. Do NOT include ClaimedBy, ClaimedByName, StaffResponse or Title.

Setup: same as oncall_relay.ps1 (script + feed_git.ps1 at the data-branch
clone root, scheduled every 5 min via run-hidden-kiosk.vbs, logged-on only).
#>
param(
    [string]$RepoPath = $PSScriptRoot,
    [string]$SourcePath = "C:\Users\travis.schaben\OneDrive - West Point\SignageFeeds\kiosk-requests-raw.json",
    [string]$TimeZoneId = "Eastern Standard Time"
)

. (Join-Path $PSScriptRoot 'feed_git.ps1')

Start-Feed -Name 'kiosk' -RepoPath $RepoPath

if (-not (Test-Path -LiteralPath $SourcePath)) {
    Exit-Feed -Code 1 -Result 'error' -Detail "source file not found: $SourcePath"
}

try {
    $parsed = Get-Content -LiteralPath $SourcePath -Raw | ConvertFrom-Json
    # Windows PowerShell 5.1 emits a JSON array as ONE object; @(...) alone would
    # wrap the whole list as a single item. Enumerate it explicitly.
    $items = @($parsed | ForEach-Object { $_ })
} catch {
    Exit-Feed -Code 1 -Result 'error' -Detail "source is not valid JSON: $SourcePath"
}

$tz = [TimeZoneInfo]::FindSystemTimeZoneById($TimeZoneId)
$todayLocal = [TimeZoneInfo]::ConvertTime([DateTime]::UtcNow, $tz).Date

function Get-State([string]$s) {
    switch -Regex ($s) {
        '^\s*Completed'      { return 'done' }
        '^\s*No Patron'      { return 'noPatron' }
        '^\s*(Auto-closed|Cancel+ed)' { return 'autoClosed' }
        default              { return 'open' }
    }
}

$today = foreach ($i in $items) {
    if (-not $i.created) { continue }
    $utc = ([DateTime]::Parse($i.created)).ToUniversalTime()
    if ([TimeZoneInfo]::ConvertTime($utc, $tz).Date -eq $todayLocal) {
        [pscustomobject]@{ Utc = $utc; Type = [string]$i.type; Status = [string]$i.status; State = (Get-State $i.status) }
    }
}
$today = @($today)

$counts = @{ open = 0; done = 0; noPatron = 0; autoClosed = 0 }
foreach ($t in $today) { $counts[$t.State]++ }

$recent = @($today | Sort-Object Utc -Descending | Select-Object -First 5 | ForEach-Object {
    $label = if ($_.State -eq 'autoClosed' -and $_.Status -notmatch 'Cancel') { 'Auto-closed' } else { $_.Status }
    [ordered]@{
        time   = $_.Utc.ToString('yyyy-MM-ddTHH:mm:ssZ')
        type   = $(if ($_.Type) { $_.Type } else { 'Help request' })
        status = $label
        state  = $(switch ($_.State) { 'open' { 'open' } 'done' { 'done' } default { 'closed' } })
    }
})

$out = [ordered]@{
    # Source file mtime, not now: a stopped flow must show STALE on the sign.
    updated = (Get-Item -LiteralPath $SourcePath).LastWriteTimeUtc.ToString('yyyy-MM-ddTHH:mm:ssZ')
    today   = [ordered]@{
        open = $counts.open; completed = $counts.done; noPatron = $counts.noPatron
        autoClosed = $counts.autoClosed; total = $today.Count
    }
    recent  = $recent
}
$json = $out | ConvertTo-Json -Depth 5

Invoke-GitOrFail -Arguments @('pull', '--rebase', 'origin', 'data') | Out-Null

$dest = Join-Path $RepoPath 'data\kiosk-requests.json'
# Skip the commit when nothing changed (updated tracks the source file).
if (Test-Path -LiteralPath $dest) {
    $old = Get-Content -LiteralPath $dest -Raw | ConvertFrom-Json
    if (($old | ConvertTo-Json -Compress -Depth 5) -eq ($out | ConvertTo-Json -Compress -Depth 5)) { Exit-Feed -Code 0 -Result 'nochange' }
}

Set-Content -LiteralPath $dest -Value $json -Encoding UTF8
Invoke-GitOrFail -Arguments @('add', 'data/kiosk-requests.json') | Out-Null
if ((Invoke-Git -Arguments @('diff', '--cached', '--quiet')).ExitCode -eq 0) { Exit-Feed -Code 0 -Result 'nochange' }
Invoke-GitOrFail -Arguments @('commit', '-m', "Update kiosk requests $(Get-Date -Format 'yyyy-MM-dd HH:mm')") | Out-Null
Invoke-FeedPush
$hash = (Invoke-Git -Arguments @('rev-parse', '--short', 'HEAD')).Output.Trim()
Exit-Feed -Code 0 -Result 'pushed' -Detail $hash
