"""Bộ thu thập: nguồn (NEO WebSocket / mô phỏng) -> kiểm tra chất lượng -> lấy mẫu -> SQLite.

Lấy mẫu theo THỜI GIAN SỰ KIỆN (không theo đồng hồ máy): mỗi mã ghi snapshot cuối cùng của mỗi
khoảng `interval_s`. Nhờ vậy cùng một logic chạy cho dữ liệu thật lẫn phát lại nhanh.
"""
from __future__ import annotations

import logging
from typing import AsyncIterator

from ..neo_api.models import Snapshot
from ..timeutil import to_vn
from .quality import QualityChecker
from .storage import Store

log = logging.getLogger("execscreen.collector")


class Sampler:
    def __init__(self, interval_s: int):
        self.interval = interval_s
        self._pending: dict[str, tuple[int, Snapshot, str, str]] = {}

    def offer(self, snap: Snapshot, phase: str, flags: str) -> tuple[Snapshot, str, str] | None:
        """Trả về snapshot của khoảng trước nếu khoảng mới bắt đầu; luôn nhớ bản mới nhất."""
        bucket = int(to_vn(snap.ts).timestamp() // self.interval)
        prev = self._pending.get(snap.symbol)
        self._pending[snap.symbol] = (bucket, snap, phase, flags)
        if prev is not None and prev[0] < bucket:
            return prev[1], prev[2], prev[3]
        return None

    def flush(self) -> list[tuple[Snapshot, str, str]]:
        out = [(s, p, f) for (_, s, p, f) in self._pending.values()]
        self._pending.clear()
        return out


async def run_collector(source: AsyncIterator[Snapshot], store: Store, checker: QualityChecker,
                        interval_s: int = 5, batch_size: int = 500, heartbeat_every: int = 200) -> dict:
    """Tiêu thụ `source` đến khi hết (mô phỏng) hoặc bị hủy (thật). Trả về thống kê."""
    sampler, buf = Sampler(interval_s), []
    n_in = 0
    src_name = "?"
    store.set_status(connected="true")
    try:
        async for snap in source:
            n_in += 1
            src_name = snap.source
            ok, flags = checker.check(snap)
            if ok:
                phase = checker.phase_of(snap)
                done = sampler.offer(snap, phase, ",".join(f for f in flags))
                if done:
                    s, p, f = done
                    buf.append(s.to_row(p, f))
            if len(buf) >= batch_size:
                store.insert_rows(buf); buf.clear()
            if n_in % heartbeat_every == 0:
                store.set_status(last_msg_ts=to_vn(snap.ts).isoformat(), msgs=n_in, source=src_name)
    except Exception as e:  # mất kết nối / lỗi nguồn: ghi trạng thái để giao diện hiển thị rõ ràng
        log.exception("Collector gặp lỗi: %s", e)
        store.set_status(connected="false", last_error=repr(e))
        raise
    finally:
        for s, p, f in sampler.flush():
            buf.append(s.to_row(p, f))
        store.insert_rows(buf)
        counts = checker.drain_counts()
        if counts:
            # gom theo ngày của dữ liệu cuối cùng nhận được (đủ cho thống kê tổng quan)
            td = to_vn(snap.ts).strftime("%Y-%m-%d") if n_in else ""
            store.add_quality(td, src_name, counts)
        store.set_status(connected="false", msgs=n_in)
    return {"received": n_in, "stored": store.count()}


class FrameSource:
    """Phát lại một DataFrame snapshot như một nguồn bất đồng bộ (dùng cho mô phỏng/kiểm thử)."""

    def __init__(self, df):
        from ..neo_api.models import snapshot_from_row
        self._rows = df.sort_values(["ts", "symbol"]).to_dict("records")
        self._conv = snapshot_from_row

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        import pandas as pd
        for r in self._rows:
            r = {k: (None if (isinstance(v, float) and v != v) else v) for k, v in r.items()}
            r["ts"] = r["ts"].isoformat() if hasattr(r["ts"], "isoformat") else r["ts"]
            if r.get("ingest_ts") is not None and hasattr(r["ingest_ts"], "isoformat"):
                r["ingest_ts"] = r["ingest_ts"].isoformat()
            yield self._conv(r)
