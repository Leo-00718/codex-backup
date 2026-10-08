#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
采集 + 整理 + 生成索引与清单。

用法:
    python backup.py                    # 备份今天（增量）
    python backup.py --full             # 全量（含所有历史 + 数据库快照）
    python backup.py --date 2026-10-07
    python backup.py --dry-run          # 只统计，不写盘

设计要点（都是踩过坑换来的）:
  1. 正在运行的 SQLite 不能直接复制 —— 用 backup API 出一致性快照，
     否则云盘可能同步到半写坏的文件。
  2. 一个跨天的长会话，文件仍在起始日期的目录里；按「文件修改时间」
     而不是「目录日期」筛选，否则跨天新增的内容会永久漏备。
  3. 凭据类文件（auth.json 等）硬编码排除，绝不进备份。
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _config  # noqa: E402

# 运行中的数据库改为快照
DB_SNAPSHOTS = [
    "thread_history_1.sqlite", "state_5.sqlite", "memories_1.sqlite",
    "goals_1.sqlite", "queue_1.sqlite",
]

# .codex 里按原路径带走的内容
CODEX_KEEP = [
    "config.toml", "AGENTS.md", "session_index.jsonl",
    ".codex-global-state.json", "skills", "automations",
    "visualizations", "attachments", "rules", "memories", "notifications",
]

INJECT_MARKERS = ("# AGENTS.md instructions", "<INSTRUCTIONS>", "<environment_context>",
                  "<app-context>", "<skills_instructions>", "<permissions instructions>",
                  "<collaboration_mode>")


def log(msg):
    print("[%s] %s" % (dt.datetime.now().strftime("%H:%M:%S"), msg), flush=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def iter_jsonl(path: Path):
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def extract_text(content):
    if isinstance(content, str):
        return content.strip()
    parts = []
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            t = item.get("text")
            if isinstance(t, str) and t.strip():
                parts.append(t.strip())
            elif item.get("type") in ("input_image", "output_image", "image"):
                parts.append("[图片]")
    return "\n\n".join(parts).strip()


def is_injected(text: str) -> bool:
    return any(m in text.lstrip()[:200] for m in INJECT_MARKERS)


def safe_copy(src: Path, dst: Path):
    """复制文件；目标已存在或只读（如 git 对象）时也能覆盖。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        try:
            os.chmod(dst, 0o666)
        except OSError:
            pass
        try:
            dst.unlink()
        except OSError:
            pass
    shutil.copy2(str(src), str(dst))   # 保留权限 + 时间戳
    if os.name == "nt":
        # Windows 上清掉只读属性方便下次覆盖；Unix 上不能无条件 chmod，
        # 否则会丢掉可执行位。
        try:
            os.chmod(dst, 0o666)
        except OSError:
            pass


def snapshot_db(src: Path, dst: Path):
    """用 SQLite backup API 出一致性快照（不碰 -wal / -shm）。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    con = sqlite3.connect(str(src))
    try:
        out = sqlite3.connect(str(dst))
        try:
            con.backup(out)
        finally:
            out.close()
    finally:
        con.close()


def walk(root: Path, cutoff=None, skip_dirs=(), skip_names=()):
    """遍历文件；跳过缓存/密钥目录，可按修改时间过滤。"""
    skip = {d for d in skip_dirs}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip and d not in skip_names]
        for fn in filenames:
            if fn in skip_names:
                continue
            p = Path(dirpath) / fn
            try:
                st = p.stat()
            except OSError:
                continue
            if cutoff and dt.datetime.fromtimestamp(st.st_mtime) < cutoff:
                continue
            yield p, st


def render_session(jsonl: Path, md: Path, out_chars=1200):
    """把会话 JSONL 转成人类可读的 Markdown。"""
    meta, blocks, user_msgs = {}, [], []
    for obj in iter_jsonl(jsonl):
        t, pl = obj.get("type"), (obj.get("payload") or {})
        if t == "session_meta":
            meta = pl
        elif t == "response_item":
            pt = pl.get("type")
            if pt == "message":
                role = pl.get("role")
                if role in ("developer", "system"):
                    continue
                text = extract_text(pl.get("content"))
                if not text:
                    continue
                if role == "user":
                    if is_injected(text):
                        continue
                    user_msgs.append(text)
                    blocks.append(("user", text))
                elif role == "assistant":
                    blocks.append(("assistant", text))
            elif pt == "function_call":
                name, args = pl.get("name") or "tool", pl.get("arguments")
                try:
                    a = json.loads(args) if isinstance(args, str) else (args or {})
                    detail = a.get("cmd") or a.get("query") or json.dumps(a, ensure_ascii=False)
                except Exception:
                    detail = str(args)
                blocks.append(("call", (name, detail[:800])))
            elif pt == "function_call_output":
                o = pl.get("output")
                if isinstance(o, str) and o.strip():
                    blocks.append(("output", o.strip()))

    if not blocks:
        return None

    sid = meta.get("id") or meta.get("session_id") or jsonl.stem
    cwd, started = meta.get("cwd") or "", meta.get("timestamp") or ""
    title = user_msgs[0].splitlines()[0][:70] if user_msgs else "(无用户消息)"

    L = ["# %s" % title, "",
         "- 会话 ID: `%s`" % sid,
         "- 开始时间: %s" % started,
         "- 工作目录: `%s`" % cwd,
         "- 来源: `%s`" % jsonl.name,
         "- 用户消息: %d 条" % len(user_msgs), "", "---", ""]

    for kind, val in blocks:
        if kind == "user":
            L += ["### 👤 我", "", val, ""]
        elif kind == "assistant":
            L += ["### 🤖 Codex", "", val, ""]
        elif kind == "call":
            name, detail = val
            L += ["<details><summary>⚙️ 执行: %s</summary>" % name, "",
                  "```", detail, "```", "", "</details>", ""]
        elif kind == "output":
            shown = val if len(val) <= out_chars else val[:out_chars] + "\n... [已截断，完整内容见 _原始数据]"
            L += ["<details><summary>📤 输出</summary>", "", "```", shown, "```", "",
                  "</details>", ""]

    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text("\n".join(L), encoding="utf-8")
    return {"file": md.name, "sid": sid, "title": title, "cwd": cwd,
            "started": started, "user_msgs": len(user_msgs)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--full", action="store_true", help="全量（含所有历史与数据库快照）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--config", default=None)
    args = ap.parse_args()

    _config.setup_stdio()
    cfg = _config.load(args.config)
    day = dt.date.fromisoformat(args.date)
    stamp = day.isoformat()
    mode = "full" if args.full else "daily"
    scope = cfg["_output"] / "archive" / mode / stamp
    cutoff = None if args.full else dt.datetime.combine(day, dt.time.min)

    log("配置: %s" % cfg["_config_path"])
    log("=== 备份  %s  (%s) ===" % (stamp, mode))
    log("输出: %s" % scope)
    if args.dry_run:
        log("DRY-RUN：只统计，不写盘")

    secret_names = set(cfg["exclude"]["secret_files"])
    secret_dirs = set(cfg["exclude"]["secret_dirs"])
    cache_dirs = set(cfg["exclude"]["cache_dirs"])
    codex = cfg["_codex"]

    st = {"sessions": 0, "msgs": 0, "works": 0, "works_bytes": 0,
          "extra": 0, "extra_bytes": 0, "dbs": 0}

    # ---------- 1. 会话 ----------
    sess_root = codex / "sessions"
    if args.full:
        files = sorted(sess_root.rglob("*.jsonl")) if sess_root.exists() else []
    else:
        files = []
        for f in (sess_root.rglob("*.jsonl") if sess_root.exists() else []):
            try:
                if dt.datetime.fromtimestamp(f.stat().st_mtime).date() == day:
                    files.append(f)
            except OSError:
                pass
        files.sort()

    conv, raw = scope / "01_对话", scope / "01_对话" / "_原始数据"
    idx_sessions = []
    for sf in files:
        info = None
        if not args.dry_run:
            info = render_session(sf, conv / (sf.stem + ".md"))
            if info:
                idx_sessions.append(info)
            dst = raw / sf.relative_to(sess_root)
            dst.parent.mkdir(parents=True, exist_ok=True)
            safe_copy(sf, dst)
        if info:
            st["msgs"] += info["user_msgs"]
        st["sessions"] += 1
    log("会话: %d 个（用户消息 %d 条）" % (st["sessions"], st["msgs"]))

    # ---------- 2. 作品文件 ----------
    works = scope / "02_作品"
    idx_works = {}
    for ws in cfg["_workspaces"]:
        if not ws.is_dir():
            continue
        for src, s in walk(ws, cutoff=cutoff, skip_dirs=cache_dirs,
                           skip_names=secret_names | secret_dirs):
            rel = src.relative_to(ws)
            st["works"] += 1
            st["works_bytes"] += s.st_size
            proj = rel.parts[0] if len(rel.parts) > 1 else "(根目录)"
            idx_works.setdefault(proj, []).append(str(rel))
            if not args.dry_run:
                safe_copy(src, works / rel)
    log("作品: %d 个文件, %s" % (st["works"], _config.human(st["works_bytes"])))

    # ---------- 3. .codex 其余数据 ----------
    sysdata = scope / "05_系统数据"
    for item in CODEX_KEEP:
        p = codex / item
        if not p.exists() or item in secret_names:
            continue
        if p.is_file():
            if cutoff and dt.datetime.fromtimestamp(p.stat().st_mtime) < cutoff:
                continue
            st["extra"] += 1
            st["extra_bytes"] += p.stat().st_size
            if not args.dry_run:
                sysdata.mkdir(parents=True, exist_ok=True)
                safe_copy(p, sysdata / item)
        else:
            for src, s in walk(p, cutoff=cutoff, skip_dirs=cache_dirs,
                               skip_names=secret_names | secret_dirs):
                st["extra"] += 1
                st["extra_bytes"] += s.st_size
                if not args.dry_run:
                    safe_copy(src, sysdata / src.relative_to(codex))
    log("系统数据: %d 个文件, %s" % (st["extra"], _config.human(st["extra_bytes"])))

    # ---------- 4. 数据库快照（仅全量） ----------
    if args.full:
        for name in DB_SNAPSHOTS:
            src = codex / name
            if not src.exists():
                continue
            if args.dry_run:
                log("  数据库快照: %s (%s)" % (name, _config.human(src.stat().st_size)))
                continue
            try:
                snapshot_db(src, sysdata / name)
                st["dbs"] += 1
            except Exception as e:
                log("  !! 快照失败 %s: %s" % (name, e))
        log("数据库快照: %d 个" % st["dbs"])
    else:
        log("数据库快照: 跳过（仅 --full 生成，避免每日重复上传）")

    if args.dry_run:
        return 0

    # ---------- 5. 索引 ----------
    L = ["# 备份索引  %s" % stamp, "",
         "- 模式: %s" % mode,
         "- 生成时间: %s" % dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
         "- 会话: %d 个" % st["sessions"],
         "- 作品文件: %d 个（%s）" % (st["works"], _config.human(st["works_bytes"])),
         "", "## 对话", ""]
    for s in sorted(idx_sessions, key=lambda x: x.get("started") or ""):
        L += ["- **%s**" % s["title"],
              "  - `%s` · %d 条用户消息 · %s" % (s["file"], s["user_msgs"], s["cwd"])]
    if not idx_sessions:
        L.append("(无)")

    L += ["", "## 作品", ""]
    for proj in sorted(idx_works):
        fl = sorted(idx_works[proj])
        L.append("- **%s** —— %d 个文件" % (proj, len(fl)))
        L += ["  - `%s`" % f for f in fl[:15]]
        if len(fl) > 15:
            L.append("  - ... 另有 %d 个" % (len(fl) - 15))
    if not idx_works:
        L.append("(无)")
    (scope / "03_索引.md").write_text("\n".join(L), encoding="utf-8")

    # ---------- 6. 清单 ----------
    manifest = []
    for p in sorted(scope.rglob("*")):
        if p.is_file() and p.name != "04_清单.json":
            manifest.append({"path": str(p.relative_to(scope)),
                             "size": p.stat().st_size, "sha256": sha256_file(p)})
    (scope / "04_清单.json").write_text(json.dumps(
        {"date": stamp, "mode": mode, "generated": dt.datetime.now().isoformat(),
         "count": len(manifest), "files": manifest}, ensure_ascii=False, indent=1),
        encoding="utf-8")

    log("索引与清单已生成：%d 个文件, %s" % (
        len(manifest), _config.human(sum(m["size"] for m in manifest))))
    log("=== 完成 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())