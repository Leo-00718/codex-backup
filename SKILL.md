---
name: "codex-backup"
description: "把 Codex 的全部数据（对话记录、产出的项目文件、配置）加密备份到云盘，以及从云端还原。当用户说\"备份一下我的Codex数据\"\"备份今天的对话\"\"全量备份\"\"还原备份\"\"恢复 Codex 数据\"时使用。"
---

# codex-backup

把 Codex 的对话记录、产出的项目文件、配置，**打包 → 加密 → 上传到云盘**。

仓库根目录假设为 `~/codex-backup`（下称 `$REPO`），请按实际安装路径替换。

---

## 一、备份

### 判断参数

| 用户说法 | 命令 |
|---|---|
| "备份今天" / "备份一下" | `python scripts/backup.py` |
| "全量备份" / "完整备份" | `python scripts/backup.py --full` |
| "备份 X 月 X 日" | `python scripts/backup.py --date 2026-10-07` |

### 执行（三件套）

```bash
# 1. 采集 + 整理 + 生成索引
python $REPO/scripts/backup.py [--full] [--date YYYY-MM-DD]

# 2. 打包（★ 关键步骤，绕开 WebDAV 请求限流）
python $REPO/scripts/pack.py --auto <full|daily> <YYYY-MM-DD>

# 3. 上传（rclone 会跳过未变文件）
rclone copy $REPO/upload/ secret: --transfers 2 --progress
```

### ⚠️ 为什么第 2 步不能省

**大多数网盘的 WebDAV 限制请求频率**（坚果云付费版：1500 次 / 30 分钟）。
上传几千个散装文件会触发限流封禁，症状是**速度平滑衰减到 0，但 rclone 不报错**。
打包成几个大文件后，请求数从约 1 万降到约 20。

**不要用 `rclone copy` 直接传未打包的备份目录。**

---

## 二、还原

```bash
# 1. 从云端拉下来
rclone copy secret: $REPO/download --progress

# 2. 预览（不改动任何东西）
python $REPO/scripts/restore.py --zips "$REPO/download/full/2026-10-07"

# 3. 真正还原
python $REPO/scripts/restore.py --zips "$REPO/download/full/2026-10-07" --apply
```

**⚠️ 还原前必须完全退出 Codex**，否则会写坏正在使用的数据库。

还原会把三样东西放回原位：

- `01_对话/_原始数据/` → `<codex_dir>/sessions/`
- `05_系统数据/` → `<codex_dir>/`
- `02_作品/` → 配置里的每个 `workspaces` 目录

---

## 三、排查问题时要知道的设计

| 设计 | 原因 |
|---|---|
| 数据库用 `backup API` 出快照 | 正在运行的 SQLite 直接复制会得到半写坏的文件，云盘同步过去就废了 |
| 会话按**文件修改时间**筛选 | 跨天的长会话文件仍在起始日期目录里，按目录日期筛会永久漏备 |
| 凭据类文件硬编码排除 | `auth.json`、`.sandbox-secrets` 等**绝不能上传**，泄露等于账号被接管 |
| 压缩包按**未压缩体积**分卷 | 保证压缩后一定小于网盘单文件上限 |
| 每个文件带 SHA256 清单 | 上传/下载后可校验完整性 |

---

## 四、安全红线（不可违反）

1. **加密密码只在用户手里** —— 不要主动索取、不要写进任何会被上传的文件。
   用户丢失密码 = 云端数据永久无法解密。
2. **`auth.json`、`.sandbox-secrets` 永不备份** —— 如果发现配置里没排除，先提醒用户。
3. **还原前确认 Codex 已退出** —— 否则不要执行 `--apply`。

---

## 五、报告给用户什么

备份完成后，汇报这几项即可：

- 会话数 / 作品文件数 / 总大小
- 打包成几个压缩包、上传是否成功
- 云端当前文件数

失败时，读 `rclone` 的输出或日志，**把原始错误贴给用户**，不要凭印象猜原因。