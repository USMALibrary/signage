<#
feed_git.ps1 - shared git plumbing for the signage feed scripts.

Dot-source this, call Start-Feed once, then route every git operation through
Invoke-Git / Invoke-GitOrFail / Invoke-FeedPush and finish with Exit-Feed.

Background: on 2026-09-30 a git process crashed and left
.git/refs/heads/data.lock behind. Every later run staged its changes, failed
to commit, and still reported success to Task Scheduler, so three feeds sat
stale for ~18 hours with nothing flagging it. Everything here exists to make
that failure mode either self-healing or loud.

Note that the repair path runs `git reset --hard origin/data`, which discards
local work. That is intentional for these feeds: every commit is pushed
immediately, so anything still local is wreckage from a crashed run.
#>

$script:FeedName       = $null
$script:FeedRepo       = $null
$script:FeedLogPath    = $null
$script:FeedLockPath   = $null
$script:FeedLockStream = $null

$script:GitTimeoutSec      = 60
$script:MutexWaitSec       = 60
$script:MutexStaleMinutes  = 10
$script:GitLockStaleMinutes = 10
$script:LogMaxBytes        = 1MB


function Write-FeedLog {
    param([string]$Result, [string]$Detail)

    $line = "{0}`t{1}`t{2}`t{3}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'),
                                    $script:FeedName,
                                    $Result,
                                    ($Detail -replace '\s+', ' ').Trim()

    try {
        $dir = Split-Path -Parent $script:FeedLogPath
        if (-not (Test-Path -LiteralPath $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
        }
        if ((Test-Path -LiteralPath $script:FeedLogPath) -and
            ((Get-Item -LiteralPath $script:FeedLogPath).Length -ge $script:LogMaxBytes)) {
            Move-Item -LiteralPath $script:FeedLogPath -Destination "$($script:FeedLogPath).1" -Force
        }
        Add-Content -LiteralPath $script:FeedLogPath -Value $line -Encoding utf8
    } catch {
        Write-Output "could not write feed log: $($_.Exception.Message)"
    }

    Write-Output $line
}


function Format-GitArgs {
    param([string[]]$Arguments)

    $parts = foreach ($a in $Arguments) {
        if ([string]::IsNullOrEmpty($a)) {
            '""'
        } elseif ($a -match '[\s"]') {
            $e = $a -replace '(\\+)(?=")', '$1$1'
            $e = $e -replace '"', '\"'
            '"' + $e + '"'
        } else {
            $a
        }
    }
    return ($parts -join ' ')
}


function Invoke-Git {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [int]$TimeoutSec = $script:GitTimeoutSec
    )

    $display = "git $($Arguments -join ' ')"

    # System.Diagnostics.Process rather than Start-Process -PassThru: the
    # latter leaves ExitCode $null unless the handle is cached, and $null -ne 0
    # made every successful call look like a failure.
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName               = 'git'
    $psi.Arguments              = Format-GitArgs -Arguments $Arguments
    $psi.WorkingDirectory       = $script:FeedRepo
    $psi.UseShellExecute        = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError  = $true
    $psi.CreateNoWindow         = $true

    $p = New-Object System.Diagnostics.Process
    $p.StartInfo = $psi

    try {
        [void]$p.Start()
    } catch {
        Exit-Feed -Code 1 -Result 'wrapper-bug' -Detail "could not start ${display}: $($_.Exception.Message)"
    }

    # Drain both pipes asynchronously; a full pipe buffer would otherwise
    # deadlock against WaitForExit.
    $outTask = $p.StandardOutput.ReadToEndAsync()
    $errTask = $p.StandardError.ReadToEndAsync()

    if (-not $p.WaitForExit($TimeoutSec * 1000)) {
        try { $p.Kill() } catch { }
        try { $p.WaitForExit() } catch { }
        return [pscustomobject]@{
            ExitCode = 124
            Output   = "$display timed out after ${TimeoutSec}s and was killed"
            TimedOut = $true
        }
    }

    # The parameterless overload flushes the redirected streams.
    try { $p.WaitForExit() } catch { }

    $out = ''
    $err = ''
    try { $out = $outTask.GetAwaiter().GetResult() } catch { }
    try { $err = $errTask.GetAwaiter().GetResult() } catch { }

    $code = $null
    try { $code = $p.ExitCode } catch { }

    if ($null -eq $code) {
        Exit-Feed -Code 1 -Result 'wrapper-bug' -Detail "no exit code available for $display"
    }

    return [pscustomobject]@{
        ExitCode = [int]$code
        Output   = ("$out`n$err").Trim()
        TimedOut = $false
    }
}


function Invoke-GitOrFail {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [int]$TimeoutSec = $script:GitTimeoutSec
    )

    $r = Invoke-Git -Arguments $Arguments -TimeoutSec $TimeoutSec
    # Only a non-zero integer is a failure; Invoke-Git has already bailed out
    # loudly if it could not read an exit code at all.
    if ($r.ExitCode -ne 0) {
        Exit-Feed -Code 1 -Result 'error' -Detail "git $($Arguments -join ' ') failed ($($r.ExitCode)): $($r.Output)"
    }
    return $r
}


function Clear-StaleGitLocks {
    $gitDir = Join-Path $script:FeedRepo '.git'
    if (-not (Test-Path -LiteralPath $gitDir)) { return }

    $cutoff = (Get-Date).AddMinutes(-$script:GitLockStaleMinutes)
    $stale = Get-ChildItem -LiteralPath $gitDir -Filter '*.lock' -Recurse -Force -ErrorAction SilentlyContinue |
             Where-Object { $_.LastWriteTime -lt $cutoff }

    foreach ($f in $stale) {
        try {
            Remove-Item -LiteralPath $f.FullName -Force
            Write-FeedLog -Result 'lock-cleared' -Detail $f.FullName
        } catch {
            Write-FeedLog -Result 'lock-stuck' -Detail "$($f.FullName): $($_.Exception.Message)"
        }
    }
}


function Repair-FeedRepoState {
    $gitDir = Join-Path $script:FeedRepo '.git'

    $reasons = @()
    foreach ($marker in @('rebase-merge', 'rebase-apply', 'MERGE_HEAD', 'CHERRY_PICK_HEAD')) {
        if (Test-Path -LiteralPath (Join-Path $gitDir $marker)) { $reasons += $marker }
    }

    $branch = (Invoke-Git -Arguments @('rev-parse', '--abbrev-ref', 'HEAD')).Output.Trim()
    if ($branch -ne 'data') { $reasons += "on branch '$branch'" }

    # Leftover staged or modified tracked files mean a previous run died between
    # `git add` and `git commit`. Every data file is regenerated each run, so
    # throwing the work away is always safe and is what unblocks the next pull.
    # Untracked files (logs, debug dumps) are deliberately ignored.
    $status = Invoke-Git -Arguments @('status', '--porcelain', '--untracked-files=no')
    if ($status.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($status.Output)) {
        $reasons += 'dirty index or working tree'
    }

    if ($reasons.Count -eq 0) { return }

    Write-FeedLog -Result 'repairing' -Detail ($reasons -join ', ')

    Invoke-Git -Arguments @('rebase', '--abort') | Out-Null
    Invoke-Git -Arguments @('merge', '--abort')  | Out-Null
    Invoke-Git -Arguments @('cherry-pick', '--abort') | Out-Null

    $fetch = Invoke-Git -Arguments @('fetch', 'origin', 'data')
    if ($fetch.ExitCode -ne 0) {
        Exit-Feed -Code 1 -Result 'error' -Detail "repair fetch failed: $($fetch.Output)"
    }

    Invoke-Git -Arguments @('checkout', '-f', 'data') | Out-Null

    $reset = Invoke-Git -Arguments @('reset', '--hard', 'origin/data')
    if ($reset.ExitCode -ne 0) {
        Exit-Feed -Code 1 -Result 'error' -Detail "repair reset failed: $($reset.Output)"
    }

    Write-FeedLog -Result 'repaired' -Detail 'reset --hard origin/data'
}


function Lock-FeedRepo {
    $deadline = (Get-Date).AddSeconds($script:MutexWaitSec)

    while ($true) {
        try {
            $script:FeedLockStream = [System.IO.File]::Open(
                $script:FeedLockPath, [System.IO.FileMode]::CreateNew,
                [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
            $w = New-Object System.IO.StreamWriter($script:FeedLockStream)
            $w.WriteLine("$($script:FeedName) $PID $(Get-Date -Format 's')")
            $w.Flush()
            return
        } catch {
            # A crashed run leaves the file behind; the OS has already released
            # the handle, so age is the only way to tell abandoned from active.
            if (Test-Path -LiteralPath $script:FeedLockPath) {
                $age = (Get-Date) - (Get-Item -LiteralPath $script:FeedLockPath).LastWriteTime
                if ($age.TotalMinutes -ge $script:MutexStaleMinutes) {
                    Write-FeedLog -Result 'mutex-stolen' -Detail "abandoned after $([math]::Round($age.TotalMinutes,1)) min"
                    Remove-Item -LiteralPath $script:FeedLockPath -Force -ErrorAction SilentlyContinue
                    continue
                }
            }
            if ((Get-Date) -ge $deadline) {
                Write-FeedLog -Result 'busy' -Detail "another feed held the git lock for over $($script:MutexWaitSec)s"
                exit 1
            }
            Start-Sleep -Seconds 2
        }
    }
}


function Unlock-FeedRepo {
    if ($script:FeedLockStream) {
        try { $script:FeedLockStream.Close() } catch { }
        $script:FeedLockStream = $null
    }
    Remove-Item -LiteralPath $script:FeedLockPath -Force -ErrorAction SilentlyContinue
}


function Start-Feed {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$RepoPath
    )

    $script:FeedName     = $Name
    $script:FeedRepo     = $RepoPath
    $script:FeedLogPath  = Join-Path $RepoPath 'logs\feeds.log'
    $script:FeedLockPath = Join-Path $RepoPath 'logs\git.lock'

    # Git must never stop for credentials: a hidden scheduled task has no one
    # to answer the prompt, and it would hang until the task limit killed it.
    $env:GIT_TERMINAL_PROMPT = '0'
    $env:GCM_INTERACTIVE     = 'never'

    if (-not (Test-Path -LiteralPath (Join-Path $RepoPath '.git'))) {
        Write-FeedLog -Result 'error' -Detail "not a git clone: $RepoPath"
        exit 1
    }

    $logDir = Join-Path $RepoPath 'logs'
    if (-not (Test-Path -LiteralPath $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }

    Set-Location -LiteralPath $RepoPath

    Lock-FeedRepo
    Clear-StaleGitLocks
    Repair-FeedRepoState
}


function Invoke-FeedPush {
    $push = Invoke-Git -Arguments @('push', 'origin', 'data')
    if ($push.ExitCode -eq 0) { return }

    $pull = Invoke-Git -Arguments @('pull', '--rebase', 'origin', 'data')
    if ($pull.ExitCode -ne 0) {
        Invoke-Git -Arguments @('rebase', '--abort') | Out-Null
        Exit-Feed -Code 1 -Result 'error' -Detail "push failed and rebase failed: $($pull.Output)"
    }

    $retry = Invoke-Git -Arguments @('push', 'origin', 'data')
    if ($retry.ExitCode -ne 0) {
        Exit-Feed -Code 1 -Result 'error' -Detail "push failed after rebase: $($retry.Output)"
    }
}


function Exit-Feed {
    param(
        [int]$Code = 0,
        [string]$Result = 'ok',
        [string]$Detail = ''
    )

    Write-FeedLog -Result $Result -Detail $Detail
    Unlock-FeedRepo
    exit $Code
}
