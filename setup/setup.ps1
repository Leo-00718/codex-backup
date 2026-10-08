# codex-backup 配置向导
# 生成 config.toml，并可选配置 rclone 远程
$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Repo = Split-Path -Parent $PSScriptRoot
$Cfg  = Join-Path $Repo 'config.toml'

Clear-Host
Write-Host ''
Write-Host '  ============================================================' -ForegroundColor Cyan
Write-Host '       codex-backup  配置向导' -ForegroundColor Cyan
Write-Host '  ============================================================' -ForegroundColor Cyan
Write-Host ''
Write-Host '  将生成 config.toml（已在 .gitignore 中，不会被提交）' -ForegroundColor DarkGray
Write-Host ''

# ---- 1. 输出目录 ----
$defaultOut = Join-Path $env:USERPROFILE 'CodexBackup'
$out = Read-Host "  备份产物目录 [$defaultOut]"
if ([string]::IsNullOrWhiteSpace($out)) { $out = $defaultOut }

# ---- 2. 工作目录 ----
Write-Host ''
Write-Host '  要一并备份的项目目录（可多个，用分号 ; 分隔，可留空）' -ForegroundColor Gray
Write-Host '  例如: D:\Projects;C:\work\my-app' -ForegroundColor DarkGray
$wsInput = Read-Host '  项目目录'
$ws = @()
if (-not [string]::IsNullOrWhiteSpace($wsInput)) {
    $ws = $wsInput -split ';' | ForEach-Object { $_.Trim() } | Where-Object { $_ }
}

# ---- 3. 写入 config.toml ----
$wsToml = ($ws | ForEach-Object { '    "' + ($_ -replace '\\','/') + '",' }) -join "`n"
if ([string]::IsNullOrWhiteSpace($wsToml)) { $wsToml = '    # "D:/Documents/MyProjects",' }

$toml = @"
# codex-backup 配置（由配置向导生成）

[general]
output_dir = "$($out -replace '\\','/')"

[source]
codex_dir = "~/.codex"
workspaces = [
$wsToml
]

[exclude]
secret_files = ["auth.json", "cap_sid", ".sandbox_migration", "installation_id"]
secret_dirs  = [".sandbox", ".sandbox-bin", ".sandbox-secrets", ".tmp", "tmp"]
cache_dirs   = ["node_modules", "__pycache__", ".venv", "venv", ".git-lfs",
                "Cache", "CachedData", "GPUCache", "Code Cache", "cache",
                "plugins", "vendor_imports", "site-packages", "dist-info"]

[pack]
# 必须小于你网盘的单文件上传上限（坚果云为 500 MB）
max_part_mb = 450

[upload]
remote = "secret:"
transfers = 2
"@
[System.IO.File]::WriteAllText($Cfg, $toml, (New-Object System.Text.UTF8Encoding($false)))
Write-Host ''
Write-Host "  [1/2] 已生成配置: $Cfg" -ForegroundColor Green

# ---- 4. 可选：配置 rclone 远程 ----
Write-Host ''
$doRclone = Read-Host '  [2/2] 现在配置 rclone 云盘远程吗？(y/N)'
if ($doRclone -eq 'y' -or $doRclone -eq 'Y') {
    Write-Host ''
    Write-Host '  以坚果云为例：' -ForegroundColor Gray
    Write-Host '    1. 登录 https://www.jianguoyun.com/' -ForegroundColor Gray
    Write-Host '    2. 账户信息 → 安全选项 → 第三方应用管理 → 添加应用密码' -ForegroundColor Gray
    Write-Host ''
    $email = Read-Host '  坚果云邮箱'
    $sec = Read-Host '  应用密码（输入时不显示）' -AsSecureString
    $b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    $pwd = [Runtime.InteropServices.Marshal]::PtrToStringAuto($b)
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b)

    $bytes = New-Object byte[] 24
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $cryptPwd = ([Convert]::ToBase64String($bytes) -replace '[+/=]','')

    Write-Host ''
    Write-Host '  ============================================================' -ForegroundColor Green
    Write-Host '     !!  请立刻把下面这行【加密密码】抄到手机备忘录  !!' -ForegroundColor Green
    Write-Host '  ============================================================' -ForegroundColor Green
    Write-Host ''
    Write-Host "        $cryptPwd" -ForegroundColor White -BackgroundColor DarkRed
    Write-Host ''
    Write-Host '     云盘里存的是乱码，只有它（+网盘账号）能解开。' -ForegroundColor Gray
    Write-Host '     丢了它 = 数据永远打不开。它不会被上传。' -ForegroundColor Gray
    Write-Host ''
    $ok = Read-Host '  抄好了吗？（输入 y 继续）'
    if ($ok -eq 'y' -or $ok -eq 'Y') {
        rclone config create nutstore webdav `
            url 'https://dav.jianguoyun.com/dav/' vendor other `
            user "$email" pass "$pwd" | Out-Null
        rclone config create secret crypt `
            remote 'nutstore:CodexBackup' password "$cryptPwd" `
            filename_encryption standard directory_name_encryption true | Out-Null
        rclone mkdir nutstore:CodexBackup
        $test = rclone lsd secret: 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host ''
            Write-Host '  [成功] 云盘连接正常，可以开始备份了。' -ForegroundColor Green
            Write-Host '  下一步：python scripts/backup.py --full' -ForegroundColor Cyan
        } else {
            Write-Host ''
            Write-Host '  [失败] 连接测试没通过：' -ForegroundColor Red
            Write-Host "  $test" -ForegroundColor DarkGray
        }
    } else {
        Write-Host '  已跳过 rclone 配置。' -ForegroundColor Yellow
    }
}

Write-Host ''
Write-Host '  配置完成。' -ForegroundColor Green
Read-Host '  按回车关闭'