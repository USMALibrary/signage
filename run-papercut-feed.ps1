# run-papercut-feed.ps1
#
# Runs papercut_status.py and, if it succeeds, commits and pushes the
# updated papercut-status.json to the signage repo (data branch).
# If the push is rejected because the remote has commits we don't have
# locally, it will automatically pull --rebase and retry the push once.
#
# Assumes:
#   - Git for Windows is installed and this repo folder is already a
#     git clone with push access configured (via a stored PAT credential).
#   - The local clone is tracking the 'data' branch.
#   - papercut_status.py lives in data\ subfolder of the repo.
#   - Required PAPERCUT_* environment variables are set at Machine scope.

$RepoPath        = "C:\Users\travis.schaben\Documents\signage"
$ScriptPath      = Join-Path $RepoPath "data\papercut_status.py"
$LogPath         = Join-Path $RepoPath "data\papercut_feed.log"
$StaleAlertPath  = Join-Path $RepoPath "STALE_ALERT.txt"
$RawJsonUrl      = "https://raw.githubusercontent.com/USMALibrary/signage/data/data/papercut-status.json"
$StaleThresholdMinutes = 20

function Write-Log($msg) {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$timestamp  $msg" | Out-File -FilePath $LogPath -Append -Encoding utf8
}

function Test-CorrectBranch {
    $branch = (git rev-parse --abbrev-ref HEAD 2>&1).Trim()
    if ($branch -ne "data") {
        Write-Log "FATAL: expected to be on branch 'data' but found '$branch' - aborting to avoid committing to the wrong branch"
        return $false
    }
    Write-Log "Branch check OK (on '$branch')"
    return $true
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

function Push-WithRetry {
    git push origin data 2>&1 | ForEach-Object { Write-Log $_ }
    if ($LASTEXITCODE -eq 0) { return $true }
    Write-Log "git push failed (exit $LASTEXITCODE) - attempting pull --rebase and retry"
    git pull --rebase origin data 2>&1 | ForEach-Object { Write-Log $_ }
    if ($LASTEXITCODE -ne 0) {
        Write-Log "git pull --rebase failed (exit $LASTEXITCODE) - giving up"
        git rebase --abort 2>&1 | ForEach-Object { Write-Log $_ }
        return $false
    }
    Write-Log "Rebase succeeded - retrying push"
    git push origin data 2>&1 | ForEach-Object { Write-Log $_ }
    if ($LASTEXITCODE -ne 0) {
        Write-Log "git push failed again after rebase - giving up"
        return $false
    }
    Write-Log "Push succeeded after retry"
    return $true
}

Set-Location $RepoPath

if (-not (Test-CorrectBranch)) {
    exit 1
}

Test-RemoteDataFreshness

Write-Log "Starting papercut_status.py"
python $ScriptPath 2>&1 | ForEach-Object { Write-Log $_ }
if ($LASTEXITCODE -ne 0) {
    Write-Log "python script failed (exit $LASTEXITCODE) - skipping git push"
    exit 1
}

git add data\papercut-status.json
$changes = git status --porcelain data\papercut-status.json
if ([string]::IsNullOrWhiteSpace($changes)) {
    Write-Log "No changes to papercut-status.json - nothing to push"
    exit 0
}

git commit -m "Update papercut-status.json ($(Get-Date -Format 'yyyy-MM-dd HH:mm'))" 2>&1 | ForEach-Object { Write-Log $_ }
$pushed = Push-WithRetry
if (-not $pushed) { exit 1 }

Write-Log "Done"