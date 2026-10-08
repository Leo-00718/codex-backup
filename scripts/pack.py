#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
打包 —— 把备份目录压成若干个小于上限的 zip。

【为什么必须打包】
  大多数网盘的 WebDAV 都限制请求频率（坚果云付费版：1500 次 / 30 分钟）。
  上传 2500 个散装文件约需 1 万次请求（每个文件 3~4 次：检查+上传+确认），
  必然触发限流，表现为速度平滑衰减到 0，最后 503 BlockedTemporarily。
  打包成 4~6 个大文件后，请求数降到约 20 次。

用法:
    python pack.py <源目录> <输出目录> [前缀]
    python pack.py --auto daily 2026-10-07        # 用配置里的路径
"""
from __future__ import annotations

import argparse
import os
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _config  # noqa: E402


def pack(src: Path, out: Path, prefix: str = "", max_part: int = 450 * 1024 * 1024):
    src, out = Path(src), Path(out)
    if not src.is_dir():
        raise SystemExit("[错误] 源目录不存在: %s" % src)
    out.mkdir(parents=True, exist_ok=True)

    parts, state = [], {"zf": None, "cur": 0, "idx": 0}

    def open_new():
        if state["zf"] is not None:
            state["zf"].close()
        state["idx"] += 1
        p = out / ("%spart%02d.zip" % (prefix, state["idx"]))
        state["zf"] = zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED, compresslevel=6)
        state["cur"] = 0
        parts.append(p)

    open_new()
    n = 0
    for dirpath, dirnames, filenames in os.walk(src):
        dirnames.sort()
        for fn in sorted(filenames):
            fp = Path(dirpath) / fn
            try:
                sz = fp.stat().st_size
            except OSError:
                continue
            if state["cur"] > 0 and state["cur"] + sz > max_part:
                open_new()
            state["zf"].write(fp, str(fp.relative_to(src)).replace("\\", "/"))
            state["cur"] += sz
            n += 1
    state["zf"].close()
    return parts, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", nargs="?", help="源目录")
    ap.add_argument("out", nargs="?", help="输出目录")
    ap.add_argument("prefix", nargs="?", default="")
    ap.add_argument("--auto", nargs=2, metavar=("MODE", "DATE"),
                    help="用配置路径打包 archive/<mode>/<date>")
    ap.add_argument("--config", default=None)
    args = ap.parse_args()

    cfg = _config.load(args.config)
    max_part = int(cfg["pack"]["max_part_mb"]) * 1024 * 1024

    if args.auto:
        mode, date = args.auto
        src = cfg["_output"] / "archive" / mode / date
        out = cfg["_output"] / "upload" / mode / date
    elif args.src and args.out:
        src, out = Path(args.src), Path(args.out)
    else:
        ap.error("请给出 <源目录> <输出目录>，或用 --auto <mode> <date>")

    parts, n = pack(Path(src), Path(out), args.prefix, max_part)
    print("源目录 : %s" % src)
    print("文件数 : %d" % n)
    print("压缩包 : %d 个（上限 %d MB）" % (len(parts), cfg["pack"]["max_part_mb"]))
    total = 0
    for p in parts:
        s = p.stat().st_size
        total += s
        print("   %-26s %s" % (p.name, _config.human(s)))
    print("合计   : %s" % _config.human(total))
    print("\n下一步: rclone copy \"%s\" %s" % (out, cfg["upload"]["remote"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())