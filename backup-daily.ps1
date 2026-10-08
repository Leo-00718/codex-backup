# 每日备份（定时任务调这个）
# 备份"昨天"的完整一天，然后打包上传
$ErrorActionPreference = 'Continue'
$Repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$Date = (Get-Date).AddDays(-1).ToString('yyyy-MM-dd')

Set-Location $Repo
New-Item -ItemType Directory -Path (Join-Path $Repo 'logs') -Force | Out-Null

Write-Host "=== codex-backup  $Date ===" -ForegroundColor Cyan

python "$Repo\scripts\backup.py" --date $Date
if ($LASTEXITCODE -ne 0) { Write-Host "采集失败，中止" -ForegroundColor Red; exit 1 }

python "$Repo\scripts\pack.py" --auto daily $Date
if ($LASTEXITCODE -ne 0) { Write-Host "打包失败，中止" -ForegroundColor Red; exit 1 }

rclone copy "$Repo\upload\" secret: --transfers 2 --retries 5 `
       --stats 30s --stats-one-line `
       --log-file "$Repo\logs\upload_$Date.log" --log-level INFO

if ($LASTEXITCODE -eq 0) {
    Write-Host "=== 完成，已上传 ===" -ForegroundColor Green
} else {
    Write-Host "=== 上传失败，见 logs\upload_$Date.log ===" -ForegroundColor Red
}