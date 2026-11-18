"""Đọc cấu hình YAML và biến môi trường."""
from __future__ import annotations

import copy
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def load_dotenv_if_present(path: Path | None = None) -> None:
    """Nạp .env đơn giản (không bắt buộc). Không ghi đè biến môi trường đã có."""
    p = path or (ROOT / ".env")
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.split("#")[0].strip())


def load_config(path: str | Path | None = None) -> dict:
    p = Path(path or os.environ.get("EXECSCREEN_CONFIG", ROOT / "config" / "screener.yaml"))
    if not p.is_absolute():
        p = ROOT / p if (ROOT / p).exists() else p
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def db_path() -> Path:
    p = Path(os.environ.get("EXECSCREEN_DB", "data/execscreen.db"))
    return p if p.is_absolute() else ROOT / p


def neo_environment() -> str:
    return os.environ.get("NEO_ENVIRONMENT", "MOCK").upper()
