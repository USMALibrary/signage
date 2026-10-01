<#
Runs the Vea visitor count feed and pushes the result to the data branch.
Intended for Windows Task Scheduler on the box that also runs the PaperCut
feed, because GitHub Actions cron only delivers ~6 of 96 requested runs/day.

All git work goes through feed_git.ps1, which handles stale locks, stuck
rebases, cross-feed mutual exclusion, timeouts and logging.

Setup:
  1. Clone the data branch (or reuse the clone the other feeds push from).
  2. Make sure this script, feed_git.ps1 and vea_visitor_count.py sit at the
     clone root.
  3. Set VEA_CLIENT_ID and VEA_CLIENT_SECRET as environment variables.
  4. Schedule every 15 minutes via run-hidden-vea.vbs.
#>
param([string]$RepoPath = $PSScriptRoot)

. (Join-Path $PSScriptRoot 'feed_git.ps1')

Start-Feed -Name 'vea' -RepoPath $RepoPath

Invoke-GitOrFail -Arguments @('pull', '--rebase', 'origin', 'data') | Out-Null

$pyOutput = & python (Join-Path $RepoPath 'vea_visitor_count.py') 2>&1
$pyExit = $LASTEXITCODE
Write-Output $pyOutput
if ($pyExit -ne 0) {
    Exit-Feed -Code 1 -Result 'error' -Detail "vea_visitor_count.py exited $pyExit"
}

Invoke-GitOrFail -Arguments @('add', 'data/visitor-count.json') | Out-Null

if ((Invoke-Git -Arguments @('diff', '--cached', '--quiet')).ExitCode -eq 0) {
    Exit-Feed -Code 0 -Result 'nochange'
}

Invoke-GitOrFail -Arguments @('commit', '-m', "Update visitor count $(Get-Date -Format 'yyyy-MM-dd HH:mm')") | Out-Null

Invoke-FeedPush

$hash = (Invoke-Git -Arguments @('rev-parse', '--short', 'HEAD')).Output.Trim()
Exit-Feed -Code 0 -Result 'pushed' -Detail $hash
