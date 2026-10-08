# codex-backup

> Back up **everything Codex produces** — conversations, project files, config —
> encrypted, to your own cloud storage. One command to back up, one to restore.

[中文说明](README.md) · [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## The problem

Everything you do in Codex lives on your local machine:

- `~/.codex/sessions/` — full conversation history (every tool call and output)
- `~/.codex/*.sqlite` — session databases
- The **project files** you produced with it

Codex has no built-in backup. If the machine dies, it's all gone.

## The key insight: why you can't just `rclone copy`

![Why packing is required](docs/assets/why-packing.svg)

This is the one non-obvious thing this project solves.

**Most WebDAV backends rate-limit requests.** For Nutstore (坚果云), the paid tier
allows **1500 requests / 30 minutes**.

Uploading 2500 individual files costs ~3-4 requests each → **~10,000 requests** →
you get throttled. The symptom is deceptive:

```
speed decays smoothly: 776 KiB/s → 21 KiB/s → 503 B/s → 0 B/s
rclone process still alive, no errors logged
API eventually returns: Too many requests are received recently: BlockedTemporarily
```

**You'd think it's a network problem. It's a request-count problem.**

**Fix: pack first, then upload.**

| | Before | After |
|---|---|---|
| Files | 2554 | **4** |
| Requests | ~10000 | **~20** |
| Size | 1635 MB | **838 MB** |

## What it does

| Feature | Notes |
|---|---|
| Full conversation backup | Raw JSONL + human-readable Markdown |
| Consistent DB snapshots | Uses SQLite `backup API` — never copies a live DB |
| Cross-day sessions | Filters by **file mtime**, not folder date |
| Credentials hard-excluded | `auth.json`, `.sandbox-secrets` are **never uploaded** |
| Auto-packing | Works around WebDAV rate limits |
| Encrypted upload | rclone crypt layer — cloud only sees gibberish |
| Self-contained restore | The restore script ships inside the backup |
| Integrity check | SHA256 manifest, verified before restore |

## Quick start

```bash
git clone https://github.com/<you>/codex-backup.git
cd codex-backup
cp config.example.toml config.toml      # edit paths

# configure cloud (rclone)
rclone config create nutstore webdav \
  url "https://dav.jianguoyun.com/dav/" vendor other \
  user "you@example.com" pass "APP_PASSWORD"
rclone config create secret crypt \
  remote "nutstore:CodexBackup" password "YOUR_ENCRYPTION_PASSWORD" \
  filename_encryption standard directory_name_encryption true
rclone mkdir nutstore:CodexBackup

# back up
python scripts/backup.py --full
python scripts/pack.py --auto full 2026-10-07
rclone copy upload/ secret: --progress

# restore
rclone copy secret: ./download --progress
python scripts/restore.py --zips "./download/full/2026-10-07"          # preview
python scripts/restore.py --zips "./download/full/2026-10-07" --apply  # write
```

> ⚠️ **Keep your encryption password safe.** It is never uploaded.
> Lose it and the cloud data is permanently unreadable.

> ⚠️ **Fully quit Codex before restoring**, or you will corrupt the live database.

## Docs

- [为什么必须打包 / Why packing](./docs/01-why-packing.md)
- [定时任务 / Scheduling](./docs/02-scheduling.md)
- [还原演练 / Restore drill](./docs/03-restore-drill.md)

> **A backup you have never restored is not a backup.** Do a restore drill.

## License

MIT