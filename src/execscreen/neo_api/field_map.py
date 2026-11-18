"""Ánh xạ tên trường của NEO API -> tên trường chuẩn của dự án, và gộp tin nhắn từng phần.

LÝ DO: tôi chưa thấy tài liệu NEO thật, nên KHÔNG đoán tên trường. Bạn điền ánh xạ vào
`config/neo_field_map.yaml` sau khi chạy `scripts/probe_neo.py` (script sẽ in ra các trường thực tế).
Mỗi loại tin (giá, sổ lệnh, nước ngoài...) có thể chỉ chứa một phần trường -> `StateMerger`
gộp theo mã để tạo snapshot đầy đủ.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..timeutil import TZ, now_vn
from .models import NUMERIC_FIELDS, Snapshot


class ParseError(ValueError):
    pass


def dig(obj: Any, path: str) -> Any:
    """Lấy giá trị theo đường dẫn 'a.b.0.c'. Không có -> None."""
    cur = obj
    for part in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def parse_ts(value: Any, fmt: str) -> datetime:
    """fmt: epoch_ms | epoch_s | iso | ymd_hms (YYYYMMDDHHMMSS, giờ VN) | hms (HH:MM:SS hôm nay, giờ VN)."""
    if value is None:
        raise ParseError("thiếu thời gian")
    try:
        if fmt == "epoch_ms":
            return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc).astimezone(TZ)
        if fmt == "epoch_s":
            return datetime.fromtimestamp(float(value), tz=timezone.utc).astimezone(TZ)
        if fmt == "iso":
            d = datetime.fromisoformat(str(value))
            return d.replace(tzinfo=TZ) if d.tzinfo is None else d.astimezone(TZ)
        if fmt == "ymd_hms":
            return datetime.strptime(str(value), "%Y%m%d%H%M%S").replace(tzinfo=TZ)
        if fmt == "hms":
            t = datetime.strptime(str(value), "%H:%M:%S").time()
            return datetime.combine(now_vn().date(), t, tzinfo=TZ)
    except (ValueError, OverflowError) as e:
        raise ParseError(f"không đọc được thời gian {value!r} theo {fmt}") from e
    raise ParseError(f"định dạng thời gian không hỗ trợ: {fmt}")


class FieldMapper:
    """mapping: {'symbol': 'path', 'ts': 'path', 'ts_format': 'epoch_ms', 'price_scale': 1000, <trường chuẩn>: 'path'}"""

    def __init__(self, mapping: dict):
        self.m = dict(mapping or {})
        self.ts_format = self.m.get("ts_format", "epoch_ms")
        self.price_scale = float(self.m.get("price_scale", 1.0))      # nhân để ra VND
        self.volume_scale = float(self.m.get("volume_scale", 1.0))    # nhân để ra cổ phiếu
        self.value_scale = float(self.m.get("value_scale", 1.0))      # nhân để ra VND
        self.paths = {k: v for k, v in self.m.items() if k in NUMERIC_FIELDS and v and v != "TODO"}

    def _scale(self, name: str, v: float) -> float:
        if name.endswith("_p") or name in ("ref", "ceiling", "floor", "last", "open", "high", "low"):
            return v * self.price_scale
        if name in ("cum_value", "fbuy_val", "fsell_val"):
            return v * self.value_scale
        return v * self.volume_scale

    def parse(self, payload: dict) -> tuple[str, datetime | None, dict]:
        """Trả về (symbol, ts hoặc None, {trường chuẩn: giá trị}) - chỉ các trường có trong tin."""
        sym_path = self.m.get("symbol")
        if not sym_path or sym_path == "TODO":
            raise ParseError("config/neo_field_map.yaml chưa khai báo 'symbol'")
        sym = dig(payload, sym_path)
        if not sym:
            raise ParseError("tin không có mã")
        ts = None
        ts_path = self.m.get("ts")
        if ts_path and ts_path != "TODO":
            raw = dig(payload, ts_path)
            if raw is not None:
                ts = parse_ts(raw, self.ts_format)
        vals = {}
        for name, path in self.paths.items():
            raw = dig(payload, path)
            if raw is None or raw == "":
                continue
            try:
                vals[name] = self._scale(name, float(raw))
            except (TypeError, ValueError):
                raise ParseError(f"trường {name} không phải số: {raw!r}")
        return str(sym).upper(), ts, vals


class StateMerger:
    """Giữ trạng thái mới nhất theo mã; mỗi tin từng phần cập nhật rồi phát snapshot đầy đủ."""

    def __init__(self, source: str = "neo"):
        self.source = source
        self.state: dict[str, dict] = {}

    def update(self, symbol: str, ts: datetime | None, vals: dict) -> Snapshot | None:
        st = self.state.setdefault(symbol, {})
        st.update(vals)
        ingest = now_vn()
        use_ts = ts or ingest
        if "last" not in st and "bid1_p" not in st:
            return None  # chưa đủ thông tin để lập snapshot
        return Snapshot(symbol, use_ts, self.source, ingest, dict(st))
