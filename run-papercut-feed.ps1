<#
run-papercut-feed.ps1

Runs papercut_status.py and, if it succeeds, commits and pushes the updated
papercut-status.json to the signage repo (data branch).

All git work goes through feed_git.ps1, which handles stale locks, stuck
rebases, cross-feed mutual exclusion, timeouts and logging. Scheduled via
run-hidden.vbs.

Assumes:
  - Git for Windows is installed and this folder is a clone with push access
    configured (via a stored PAT credential).
  - feed_git.ps1 sits at the clone root.
  - papercut_status.py lives in the data\ subfolder of the repo.
  - Required PAPERCUT_* environment variables are set at Machine scope.
#>
param([string]$RepoPath = "C:\Users\travis.schaben\Documents\signage")

. (Join-Path $PSScriptRoot 'feed_git.ps1')

$ScriptPath     = Join-Path $RepoPath "data\papercut_status.py"
$LogPath        = Join-Path $RepoPath "data\papercut_feed.log"
$StaleAlertPath = Join-Path $RepoPath "STALE_ALERT.txt"
$RawJsonUrl     = "https://raw.githubusercontent.com/USMALibrary/signage/data/data/papercut-status.json"
$StaleThresholdMinutes = 20

function Write-Log($msg) {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$timestamp  $msg" | Out-File -FilePath $LogPath -Append -Encoding utf8
}

function Test-RemoteDataFreshness {
    try {
        $response = Invoke-RestMethod -Uri $RawJsonUrl -TimeoutSec 15
        $updated  = [datetime]::Parse($response.updated).ToUniversalTime()
        $ageMinutes = ((Get-Date).ToUniversalTime() - $updated).TotalMinutes

        if ($ageMinutes -gt $StaleThresholdMinutes) {
            $msg = "STALE-ALERT: remote papercut-status.json is $([math]::Round($ageMinutes,1)) minutes old (threshold: $StaleThresholdMinutes) - recent runs may be failing"
            Write-Log $msg
            $msg | Out-File -FilePath $StaleAlertPath -Encoding utf8
        }
        else {
            Write-Log "Remote data freshness OK ($([math]::Round($ageMinutes,1)) min old)"
            if (Test-Path $StaleAlertPath) { Remove-Item $StaleAlertPath -Force }
        }
    }
    catch {
        Write-Log "WARNING: could not check remote data freshness - $($_.Exception.Message)"
    }
}

Start-Feed -Name 'papercut' -RepoPath $RepoPath

Test-RemoteDataFreshness

Write-Log "Starting papercut_status.py"
$pyOutput = & python $ScriptPath 2>&1
$pyExit = $LASTEXITCODE
$pyOutput | ForEach-Object { Write-Log $_ }
if ($pyExit -ne 0) {
    Write-Log "python script failed (exit $pyExit) - skipping git push"
    Exit-Feed -Code 1 -Result 'error' -Detail "papercut_status.py exited $pyExit"
}

Invoke-GitOrFail -Arguments @('add', 'data/papercut-status.json') | Out-Null

if ((Invoke-Git -Arguments @('diff', '--cached', '--quiet')).ExitCode -eq 0) {
    Write-Log "No changes to papercut-status.json - nothing to push"
    Exit-Feed -Code 0 -Result 'nochange'
}

Invoke-GitOrFail -Arguments @('commit', '-m', "Update papercut-status.json ($(Get-Date -Format 'yyyy-MM-dd HH:mm'))") | Out-Null

Invoke-FeedPush

$hash = (Invoke-Git -Arguments @('rev-parse', '--short', 'HEAD')).Output.Trim()
Write-Log "Pushed $hash"
Exit-Feed -Code 0 -Result 'pushed' -Detail $hash
