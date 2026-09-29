<#
Runs the Vea visitor count feed and pushes the result to the data branch.
Intended for Windows Task Scheduler on the box that also runs the PaperCut feed,
because GitHub Actions cron only delivers ~6 of 96 requested runs per day.

Setup:
  1. Clone the data branch:
       git clone -b data https://github.com/USMALibrary/signage.git C:\signage-data
     (or reuse the clone the PaperCut task already pushes from)
  2. Make sure this script and vea_visitor_count.py sit at the clone root.
     Pulling the data branch brings both down.
  3. Set VEA_CLIENT_ID and VEA_CLIENT_SECRET as machine environment variables.
  4. Schedule this script every 15 minutes:
       powershell -ExecutionPolicy Bypass -File C:\signage-data\vea_visitor_count.ps1
#>
param([string]$RepoPath = $PSScriptRoot)

Set-Location $RepoPath

git pull --rebase origin data

python vea_visitor_count.py
if ($LASTEXITCODE -ne 0) {
    Write-Error "vea_visitor_count.py exited $LASTEXITCODE - nothing committed"
    exit 1
}

git add data/visitor-count.json
git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Output "No changes to commit"
    exit 0
}

git commit -m "Update visitor count $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
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
