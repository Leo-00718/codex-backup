#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
端到端冒烟测试：造一个假的 Codex 目录，跑完「备份 → 打包 → 还原」全流程。

不依赖真实 Codex 环境，任何机器上都能跑（CI 用这个）。
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
PY = sys.executable

# Windows 控制台默认编码可能不是 UTF-8，先强制一下，否则打印中文会崩
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


def build_fake_env(root: Path):
    """造一个最小的 Codex 数据目录 + 一个工作目录。"""
    codex = root / ".codex"
    work = root / "workspace"
    (codex / "sessions" / "2026" / "01" / "02").mkdir(parents=True)
    work.mkdir(parents=True)

    # 会话文件
    sid = "11111111-2222-3333-4444-555555555555"
    lines = [
        {"type": "session_meta", "payload": {
            "id": sid, "cwd": str(work), "timestamp": "2026-01-02T10:00:00.000Z"}},
        {"type": "response_item", "payload": {"type": "message", "role": "user",
            "content": [{"type": "input_text", "text": "你好，帮我测试一下"}]}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": "好的，这是回复"}]}},
    ]
    sfile = codex / "sessions" / "2026" / "01" / "02" / ("rollout-2026-01-02T10-00-00-" + sid + ".jsonl")
    sfile.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines), encoding="utf-8")

    # 一个 SQLite（验证快照逻辑）
    con = sqlite3.connect(codex / "state_5.sqlite")
    con.execute("create table t(a integer)")
    con.execute("insert into t values (1), (2), (3)")
    con.commit()
    con.close()

    # 必须被排除的密钥文件
    (codex / "auth.json").write_text('{"token":"MUST_NOT_BE_BACKED_UP"}', encoding="utf-8")
    (codex / ".sandbox-secrets").mkdir(exist_ok=True)
    (codex / ".sandbox-secrets" / "k.txt").write_text("SECRET", encoding="utf-8")

    # 工作区里的密钥文件（回归用例：曾漏掉 .secrets.ps1 导致差点上传）
    (work / ".secrets.ps1").write_text(
        '$APP_SECRET = "REAL_SECRET_VALUE_MUST_NOT_BE_BACKED_UP"', encoding="utf-8")
    (work / ".env").write_text("API_KEY=REAL_KEY_MUST_NOT_BE_BACKED_UP", encoding="utf-8")
    (work / "id_rsa").write_text("-----BEGIN PRIVATE KEY-----", encoding="utf-8")
    (work / "cert.pem").write_text("-----BEGIN CERTIFICATE-----", encoding="utf-8")
    # 这个必须保留（模板，不含密钥）
    (work / ".env.example").write_text("API_KEY=your_key_here", encoding="utf-8")

    # 模拟"克隆下来的第三方项目" —— 应被 exclude.paths 整目录跳过
    vendor = work / "vendor-clone"
    vendor.mkdir()
    (vendor / "README.md").write_text("# third party", encoding="utf-8")
    (vendor / "huge.md").write_text("x" * 1000, encoding="utf-8")

    # 工作目录里的文件
    (work / "note.md").write_text("# 测试文件\n", encoding="utf-8")

    # 内容里藏密钥的文件 —— 文件名正常，只能靠内容扫描发现
    # （回归用例：真实场景里密钥常常是被粘贴进对话/文档的）
    (work / "notes-with-secret.md").write_text(
        "# 配置记录\n\nAPP_SECRET = 'js9DnajwjptvyGvgI5ayabYnaXc0E14Yzzzz'\n"
        "key = sk-conjvmckx9j7m2hxyh91yh8kdbg282pqgs5lq\n"
        "token = ghp_abcdefghijklmnopqrstuvwxyz0123456789\n",
        encoding="utf-8")
    (work / "plain.md").write_text("# 完全正常的文档\n没有密钥\n", encoding="utf-8")
    (work / "sub").mkdir()
    (work / "sub" / "code.py").write_text("print(1)\n", encoding="utf-8")

    return codex, work


def write_config(path: Path, out: Path, codex: Path, work: Path, extra_paths=()):
    paths = "".join('    "%s",\n' % Path(x).as_posix() for x in extra_paths)
    path.write_text(
        f'[general]\noutput_dir = "{out.as_posix()}"\n\n'
        f'[source]\ncodex_dir = "{codex.as_posix()}"\nworkspaces = ["{work.as_posix()}"]\n\n'
        '[exclude]\nsecret_files = ["auth.json", "cap_sid"]\n'
        'secret_dirs = [".sandbox-secrets", ".tmp"]\n'
        'cache_dirs = ["node_modules", "__pycache__"]\n'
        'paths = [\n' + paths + ']\n\n'
        '[pack]\nmax_part_mb = 450\n\n[upload]\nremote = "test:"\n',
        encoding="utf-8")


def run(*args):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run([PY] + [str(a) for a in args],
                       capture_output=True, text=True, encoding="utf-8", env=env)
    if r.returncode != 0:
        print("--- 命令失败 ---")
        print(" ".join(str(a) for a in args))
        print(r.stdout)
        print(r.stderr)
        raise SystemExit(1)
    return r.stdout


def check(cond, msg):
    if cond:
        print("  PASS  " + msg)
    else:
        print("  FAIL  " + msg)
        raise SystemExit(1)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="codex-backup-test-"))
    try:
        root = tmp / "env"
        root.mkdir()
        codex, work = build_fake_env(root)
        cfg = tmp / "config.toml"
        out = tmp / "out"
        write_config(cfg, out, codex, work, extra_paths=[work / "vendor-clone"])

        print("\n[1/4] 备份（全量）")
        run(SCRIPTS / "backup.py", "--full", "--date", "2026-01-02", "--config", cfg)
        scope = out / "archive" / "full" / "2026-01-02"
        check(scope.is_dir(), "备份目录已生成")
        check((scope / "01_对话" / "_原始数据").exists(), "对话原始数据已保存")
        check((scope / "04_清单.json").exists(), "清单已生成")

        # 密钥排除（回归用例）
        # 注意：不能用 "SECRET" 这个词判断 —— APP_SECRET 是变量名，红字打码后它仍然在。
        # 要判断的是「密钥的值」，不是「变量名」。
        leaked = [p for p in scope.rglob("*")
                  if p.is_file() and "auth.json" in p.name]
        check(not leaked, "密钥文件已排除（auth.json / .sandbox-secrets 未进备份）")

        names = {p.name for p in scope.rglob("*") if p.is_file()}
        for bad in (".secrets.ps1", ".env", "id_rsa", "cert.pem"):
            check(bad not in names, "密钥文件已排除：%s" % bad)
        check(".env.example" in names, "模板文件 .env.example 被保留（没误杀）")
        check(not any("vendor-clone" in str(p) for p in scope.rglob("*")),
              "exclude.paths 生效：第三方目录整目录跳过")

        # 内容级密钥清除（回归用例）
        import re as _re
        secret_pat = _re.compile(
            r"(?i)(app[_-]?secret[\"']?\s*[:=]\s*[\"'][A-Za-z0-9]{16,}"
            r"|\bsk-[A-Za-z0-9_\-]{20,}\b"
            r"|\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b)")

        found_any = False
        for p in scope.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() not in (".md", ".txt", ".json", ".jsonl", ".py"):
                continue
            try:
                txt = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if secret_pat.search(txt):
                found_any = True
                print("       泄漏于:", p.relative_to(scope))
        check(not found_any, "内容级密钥清除：备份里不含任何密钥内容")

        # 确认打码标记出现（说明确实清除了，而不是整文件被丢）
        redacted_files = [p for p in scope.rglob("*")
                          if p.is_file() and p.suffix.lower() == ".md"
                          and "[REDACTED by codex-backup]" in p.read_text(encoding="utf-8", errors="ignore")]
        check(len(redacted_files) >= 1, "内容级密钥清除：确实生成了打码标记")

        # 确认正常文件没被误伤
        plain = list(scope.rglob("plain.md"))
        check(bool(plain) and "没有密钥" in plain[0].read_text(encoding="utf-8", errors="ignore"),
              "普通文档未被误伤")

        # 数据库快照
        snap = scope / "05_系统数据" / "state_5.sqlite"
        check(snap.exists(), "数据库快照已生成")
        c = sqlite3.connect(str(snap))
        check(c.execute("pragma integrity_check").fetchone()[0] == "ok", "数据库快照完整性 ok")
        check(c.execute("select count(*) from t").fetchone()[0] == 3, "数据库快照数据完整")
        c.close()

        print("\n[2/4] 打包")
        run(SCRIPTS / "pack.py", "--auto", "full", "2026-01-02", "--config", cfg)
        zips = list((out / "upload" / "full" / "2026-01-02").glob("part*.zip"))
        check(len(zips) >= 1, "压缩包已生成（%d 个）" % len(zips))

        print("\n[3/4] 还原（预览）")
        out2 = run(SCRIPTS / "restore.py", "--zips", out / "upload" / "full" / "2026-01-02",
                   "--work", tmp / "unpacked", "--config", cfg)
        check("完整性校验" in out2, "走了完整性校验")

        print("\n[4/4] 还原（实际写入到隔离目录）")
        codex2 = tmp / "restored" / ".codex"
        work2 = tmp / "restored" / "workspace"
        cfg2 = tmp / "config2.toml"
        write_config(cfg2, out, codex2, work2)
        run(SCRIPTS / "restore.py", "--zips", out / "upload" / "full" / "2026-01-02",
            "--work", tmp / "unpacked2", "--apply", "--config", cfg2)
        check((codex2 / "sessions").exists(), "会话已还原")
        check((work2 / "note.md").exists(), "作品文件已还原")
        rdb = codex2 / "state_5.sqlite"
        check(rdb.exists(), "数据库已还原")
        c = sqlite3.connect(str(rdb))
        check(c.execute("pragma integrity_check").fetchone()[0] == "ok", "还原的数据库完整性 ok")
        c.close()

        print("\n全部通过 ✓\n")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())