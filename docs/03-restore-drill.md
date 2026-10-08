# 还原演练

> **没做过还原演练的备份，不能算备份。**

这句话不是口号。加密备份最常见的翻车方式是：

```
数据完好无损地躺在云盘里
但你打不开它
```

因为解密需要的东西（密码 / 配置文件）也在那台坏掉的电脑上。

---

## 一、先确认你手上有这三样

| # | 东西 | 存在哪 |
|---|---|---|
| 1 | 网盘账号 + 密码 | 你脑子里 / 密码管理器 |
| 2 | 网盘「应用密码」（如果是坚果云等） | 同上 |
| 3 | **rclone crypt 加密密码** | **逃生包：手机备忘录 / 纸上 / 密码管理器** |

**第 3 项是唯一无法从别处找回的。**
rclone 配置文件里存的是**混淆后**的密码（可逆），所以配置文件本身也必须妥善保管，
但它也可以**在新电脑上用密码重新生成**——前提是你记得密码。

> 💡 **建议**：把「网盘地址 + 应用密码 + 加密密码」写在一张纸上，和身份证分开放。
> 或者存进密码管理器（Bitwarden / 1Password / KeePass）。

---

## 二、演练步骤（建议每季度一次）

**目标：在一台"干净"的环境里，从云盘把数据完整恢复出来。**

### 1. 从云端拉取

```bash
rclone copy secret: ./drill/download --progress
```

### 2. 预览还原（不改动任何东西）

```bash
python scripts/restore.py \
  --zips "./drill/download/full/2026-10-07" \
  --work "./drill/unpacked"
```

这一步会：
- 解压压缩包
- 对比清单里的 SHA256，报告异常
- 列出将要还原的文件（**不实际写入**）

### 3. 还原到隔离目录（不碰真实数据）

用 `--config` 指向一个临时配置，把目标指向临时目录：

```bash
# drill-config.toml
# [source]
# codex_dir = "./drill/restored/.codex"
# workspaces = ["./drill/restored/projects"]
```

```bash
python scripts/restore.py \
  --zips "./drill/download/full/2026-10-07" \
  --apply --config ./drill-config.toml
```

### 4. 验证还原结果

- [ ] 目录结构完整
- [ ] 数据库能打开（`sqlite3 xxx.sqlite "pragma integrity_check;"` 返回 `ok`）
- [ ] 随机抽几个文件，和原位置比对 SHA256
- [ ] 对话记录能被解析

---

## 三、真正的灾难恢复流程

如果电脑真的坏了，在**新电脑**上：

### 1. 装环境

- 装 Codex 桌面版，打开一次（让它生成空白的 `~/.codex`）
- **完全退出 Codex**
- 装 Python 和 rclone

### 2. 重建 rclone 配置

```bash
rclone config create nutstore webdav \
  url "https://dav.jianguoyun.com/dav/" \
  vendor other user "你的邮箱" pass "你的应用密码"

rclone config create secret crypt \
  remote "nutstore:CodexBackup" \
  password "你的加密密码" \
  filename_encryption standard directory_name_encryption true
```

### 3. 拉取 + 还原

```bash
rclone copy secret: ./download --progress
python scripts/restore.py --zips "./download/full/<日期>" --apply
```

### 4. 验证

打开 Codex，检查：
- [ ] 左侧能看到过去的会话列表
- [ ] 随便点开一个旧会话，内容完整
- [ ] 项目文件回来了

---

## 四、为什么用 SQLite 快照而不是直接拷数据库

还原时你会看到 `thread_history_1.sqlite` 这类文件。

**它们不是原始数据库文件，是一致性快照。**

因为 Codex 运行时数据库一直在写（有 `-wal` / `-shm` 伴生文件）。
直接复制可能得到**写了一半的状态**，而且云盘同步时很可能只同步了一部分。

`backup.py` 用 SQLite 官方的 `backup API` 生成快照，
这是官方推荐的做法，能保证**文件内部一致**。