# 定时任务

## 设计原则

**备份"前一天"的完整一天，而不是"今天到目前为止"。**

如果定时任务设在 23:00，而你 23:30 还在干活，那一部分就漏了。
所以放在**凌晨**跑，备份**昨天**。

另外要开启「错过后补跑」——如果凌晨电脑是关着的，开机后自动补。

## Windows（任务计划程序）

```powershell
# 包装脚本：backup-daily.ps1
$ErrorActionPreference = 'Continue'
$repo = 'D:\GitHub\codex-backup'
$date = (Get-Date).AddDays(-1).ToString('yyyy-MM-dd')

Set-Location $repo

python "$repo\scripts\backup.py" --date $date
python "$repo\scripts\pack.py" --auto daily $date
rclone copy "$repo\upload\" secret: --transfers 2 --retries 5 `
       --log-file "$repo\logs\upload_$date.log" --log-level INFO
```

注册任务：

```powershell
$action  = New-ScheduledTaskAction -Execute 'powershell.exe' `
  -Argument '-NoProfile -ExecutionPolicy Bypass -File "D:\GitHub\codex-backup\backup-daily.ps1"'
$trigger = New-ScheduledTaskTrigger -Daily -At 02:00
$settings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `            # 错过了就补跑
  -MultipleInstances IgnoreNew `   # 不并发
  -ExecutionTimeLimit (New-TimeSpan -Hours 4)

Register-ScheduledTask -TaskName 'CodexBackup' `
  -Action $action -Trigger $trigger -Settings $settings -Force
```

## macOS / Linux（crontab）

```cron
# 每天 02:00 备份昨天
0 2 * * * /path/to/codex-backup/backup-daily.sh >> /path/to/codex-backup/logs/cron.log 2>&1
```

`backup-daily.sh`：

```bash
#!/usr/bin/env bash
set -euo pipefail
REPO="$(cd "$(dirname "$0")" && pwd)"
DATE=$(date -d yesterday +%F 2>/dev/null || date -v-1d +%F)
cd "$REPO"
python3 scripts/backup.py --date "$DATE"
python3 scripts/pack.py --auto daily "$DATE"
rclone copy upload/ secret: --transfers 2 --retries 5
```

> macOS 的 `date` 语法和 Linux 不同，脚本里做了兼容。

## 每周一次全量

增量备份只包含"当天改动"。为了能快速还原一个完整状态，
建议**每周做一次全量**（含所有历史会话 + 数据库快照）。

全量比增量重得多（数据库快照约 200 MB+），所以不要每天做。

```cron
# 每周日 03:00 全量
0 3 * * 0 /path/to/codex-backup/backup-full.sh
```