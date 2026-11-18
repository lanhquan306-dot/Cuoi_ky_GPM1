"""Mô hình dữ liệu chuẩn hóa (canonical). Mọi nguồn (NEO, mô phỏng) đều quy về `Snapshot`.

Đơn vị: giá = VND; khối lượng = cổ phiếu; giá trị = VND; thời gian = Asia/Ho_Chi_Minh.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime

from ..timeutil import to_vn

LEVEL_FIELDS = [f"{s}{i}_{k}" for s in ("bid", "ask") for i in (1, 2, 3) for k in ("p", "v")]

# Các cột số của snapshot (ngoài symbol, ts, source...)
NUMERIC_FIELDS = [
    "ref", "ceiling", "floor", "last", "open", "high", "low",
    "cum_volume", "cum_value",
    *LEVEL_FIELDS,
    "fbuy_vol", "fsell_vol", "fbuy_val", "fsell_val", "room_cur", "room_total",
]


@dataclass
class Snapshot:
    symbol: str
    ts: datetime
    source: str = "neo"
    ingest_ts: datetime | None = None
    values: dict = field(default_factory=dict)   # canonical numeric field -> float

    def get(self, name: str) -> float:
        v = self.values.get(name)
        return float("nan") if v is None else float(v)

    def to_row(self, phase: str = "", flags: str = "") -> dict:
        row = {"symbol": self.symbol, "ts": to_vn(self.ts).isoformat(),
               "trade_date": to_vn(self.ts).strftime("%Y-%m-%d"),
               "source": self.source, "phase": phase, "q_flags": flags,
               "ingest_ts": to_vn(self.ingest_ts).isoformat() if self.ingest_ts else None}
        for k in NUMERIC_FIELDS:
            v = self.values.get(k)
            row[k] = None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)
        return row


def snapshot_from_row(row: dict) -> Snapshot:
    ts = datetime.fromisoformat(row["ts"])
    ing = datetime.fromisoformat(row["ingest_ts"]) if row.get("ingest_ts") else None
    vals = {k: row.get(k) for k in NUMERIC_FIELDS if row.get(k) is not None}
    return Snapshot(row["symbol"], ts, row.get("source", "?"), ing, vals)
