#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
还原 —— 把云端的备份恢复回本机。

流程：解压 → 校验清单 → 按原始位置还原

用法:
    # 先下载：rclone copy secret: <下载目录>
    python restore.py --zips "<下载目录>"                # 预览
    python restore.py --zips "<下载目录>" --apply         # 真正写入

⚠️ 运行前请完全退出 Codex，否则会写坏正在使用的数据库。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _config  # noqa: E402


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1024 * 1024), b""):
            h.update(c)
    return h.hexdigest()


def safe_copy(src: Path, dst: Path):
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
    shutil.copy2(str(src), str(dst))
    if os.name == "nt":
        try:
            os.chmod(dst, 0o666)
        except OSError:
            pass


def unpack(zips_dir: Path, work: Path):
    parts = sorted(zips_dir.glob("part*.zip"))
    if not parts:
        return None
    work.mkdir(parents=True, exist_ok=True)
    print("   找到 %d 个压缩包 → 解压到 %s" % (len(parts), work))
    n = 0
    for zp in parts:
        with zipfile.ZipFile(zp) as z:
            z.extractall(work)
            # zipfile 不会恢复 Unix 权限位（可执行位会丢），手动补上
            if os.name != "nt":
                for info in z.infolist():
                    mode = (info.external_attr >> 16) & 0o777
                    if mode:
                        try:
                            os.chmod(work / info.filename, mode)
                        except OSError:
                            pass
            n += len(z.namelist())
        print("     %-28s 已解压" % zp.name)
    print("   共解压 %d 个条目" % n)
    return work


def copy_tree(src: Path, dst: Path, apply: bool, label: str, stats: dict):
    if not src.exists():
        print("  [跳过] %s（不存在）" % label)
        return
    shown = 0
    for dirpath, _, filenames in os.walk(src):
        for fn in filenames:
            s = Path(dirpath) / fn
            d = dst / s.relative_to(src)
            stats["files"] += 1
            stats["bytes"] += s.stat().st_size
            if apply:
                safe_copy(s, d)
            if shown < 3:
                print("     %s" % s.relative_to(src))
                shown += 1
    print("  [%s] %s" % ("已还原" if apply else "将还原", label))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zips", help="含 part*.zip 的目录")
    ap.add_argument("--archive", help="已解压的备份目录")
    ap.add_argument("--work", default=None, help="解压到哪里（默认 <output>/unpacked）")
    ap.add_argument("--apply", action="store_true", help="真正写入；默认仅预览")
    ap.add_argument("--skip-verify", action="store_true")
    ap.add_argument("--config", default=None)
    args = ap.parse_args()

    cfg = _config.load(args.config)
    if not args.zips and not args.archive:
        ap.error("请用 --zips 指向压缩包目录，或用 --archive 指向已解压目录")

    work = Path(args.work) if args.work else cfg["_output"] / "unpacked"
    src = Path(args.archive) if args.archive else work

    print("=" * 64)
    print("codex-backup  还原")
    print("  Codex 目录: %s" % cfg["_codex"])
    print("  工作目录  : %s" % (", ".join(str(w) for w in cfg["_workspaces"]) or "(未配置)"))
    print("  模式      : %s" % ("真正写入" if args.apply else "预览（加 --apply 才写入）"))
    print("=" * 64)

    if args.zips:
        print("\n[1/3] 解压")
        if unpack(Path(args.zips), work) is None:
            print("   !! 没找到 part*.zip")
            return 1
        src = work
    else:
        print("\n[1/3] 跳过解压")

    mf = src / "04_清单.json"
    if mf.exists() and not args.skip_verify:
        try:
            m = json.loads(mf.read_text(encoding="utf-8"))
            bad = [f["path"] for f in m.get("files", [])
                   if not (src / f["path"]).exists()
                   or (src / f["path"]).stat().st_size != f["size"]]
            print("\n[2/3] 完整性校验: 共 %d 个文件，异常 %d 个"
                  % (m.get("count", 0), len(bad)))
            for b in bad[:10]:
                print("   !! %s" % b)
        except Exception as e:
            print("\n[2/3] 清单读取失败: %s（继续）" % e)
    else:
        print("\n[2/3] 跳过完整性校验")

    print("\n[3/3] 还原")
    stats = {"files": 0, "bytes": 0}
    codex = cfg["_codex"]

    copy_tree(src / "01_对话" / "_原始数据", codex / "sessions", args.apply,
              "对话原始数据 → %s/sessions" % codex, stats)
    copy_tree(src / "05_系统数据", codex, args.apply, "系统数据 → %s" % codex, stats)
    for ws in cfg["_workspaces"]:
        if (src / "02_作品").exists():
            copy_tree(src / "02_作品", ws, args.apply, "作品 → %s" % ws, stats)

    print("\n合计: %d 个文件, %s" % (stats["files"], _config.human(stats["bytes"])))
    if not args.apply:
        print("\n这是预览。确认无误后加 --apply 再跑一次。")
        print("⚠️ 还原前请完全退出 Codex。")
    else:
        print("\n还原完成。请重新打开 Codex 查看。")
    return 0


if __name__ == "__main__":
    sys.exit(main())