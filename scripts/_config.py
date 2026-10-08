#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配置加载（各脚本共用）"""
from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    import tomllib as _toml          # Python 3.11+
except ImportError:                   # pragma: no cover
    try:
        import tomli as _toml         # pip install tomli
    except ImportError:
        _toml = None

DEFAULTS = {
    "general": {"output_dir": "~/CodexBackup"},
    "source": {"codex_dir": "~/.codex", "workspaces": []},
    "exclude": {
        # 默认就排除常见密钥文件，避免用户忘了配
        "secret_files": [
            "auth.json", "cap_sid", ".sandbox_migration", "installation_id",
            ".secrets.ps1", ".secrets", "secrets.ps1", "secrets.json",
            "credentials.json", "id_rsa", "id_ed25519",
            ".npmrc", ".pypirc", ".netrc",
            ".env", ".env.local", ".env.production", ".env.development",
        ],
        "secret_dirs": [".sandbox", ".sandbox-secrets", ".tmp", "tmp"],
        "cache_dirs": [
            "node_modules", "__pycache__", ".venv", "venv", ".git-lfs",
            "Cache", "CachedData", "GPUCache", "Code Cache", "plugins",
            "vendor_imports", "site-packages", "dist-info",
        ],
        "secret_globs": ["*.pem", "*.key", "*.pfx", "*.p12"],
        # 整目录排除（第三方项目 / 可重新下载的东西）
        "paths": [],
    },
    "pack": {"max_part_mb": 450},
    "upload": {"remote": "secret:", "transfers": 2},
}


def setup_stdio():
    """强制标准输出/错误用 UTF-8。

    为什么需要：Windows 控制台默认编码不一定是 UTF-8
    （英文版是 cp1252，中文版是 cp936），
    打印中文日志时会抛 UnicodeEncodeError 直接崩掉。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def expand(p: str) -> Path:
    """展开 ~ 和 %VAR% / $VAR 环境变量。"""
    p = os.path.expandvars(os.path.expanduser(str(p)))
    return Path(p)


def _merge(base: dict, override: dict) -> dict:
    out = {k: dict(v) if isinstance(v, dict) else v for k, v in base.items()}
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def find_config(explicit: str | None = None) -> Path | None:
    """按优先级找配置文件。"""
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("CODEX_BACKUP_CONFIG"):
        candidates.append(Path(os.environ["CODEX_BACKUP_CONFIG"]))
    here = Path(__file__).resolve().parent.parent       # 仓库根
    candidates += [here / "config.toml", here / "config.example.toml"]
    candidates.append(Path.home() / ".codex-backup.toml")
    for c in candidates:
        if c.is_file():
            return c
    return None


def load(explicit: str | None = None) -> dict:
    """载入配置，与默认值合并。"""
    path = find_config(explicit)
    data = {}
    if path:
        if _toml is None:
            sys.exit("[错误] 需要 Python 3.11+，或先执行：pip install tomli")
        with open(path, "rb") as f:
            data = _toml.load(f)
    cfg = _merge(DEFAULTS, data)

    # 安全红线：密钥类的排除规则只能「追加」，不能被配置文件覆盖掉。
    # 否则用户写了一份自己的 secret_files，就会静默丢掉内置的保护
    # （踩过的坑：曾因此差点把 .secrets.ps1 传上云盘）。
    for key in ("secret_files", "secret_dirs", "secret_globs"):
        merged = list(DEFAULTS["exclude"].get(key, []))
        for item in (cfg["exclude"].get(key) or []):
            if item not in merged:
                merged.append(item)
        cfg["exclude"][key] = merged

    cfg["_config_path"] = str(path) if path else "(使用内置默认值)"

    cfg["_output"] = expand(cfg["general"]["output_dir"])
    cfg["_codex"] = expand(cfg["source"]["codex_dir"])
    cfg["_workspaces"] = [expand(w) for w in cfg["source"].get("workspaces", [])]
    return cfg


def human(n: float) -> str:
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return "%.1f %s" % (n, u)
        n /= 1024.0