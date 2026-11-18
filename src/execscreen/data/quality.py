"""Kiểm tra chất lượng dữ liệu theo thời gian thực (trước khi lưu).

Mã sự cố:
  Loại bỏ (không lưu):
    NO_SYMBOL, BAD_TS, FUTURE_TS, DUPLICATE, OUT_OF_ORDER, NEG_VALUE,
    CUM_DECREASE (khối lượng/giá trị cộng dồn giảm trong cùng ngày),
    OUT_OF_BAND (giá ngoài [sàn, trần]), CROSSED_BOOK (mua >= bán trong phiên liên tục)
  Giữ nhưng gắn cờ (q_flags):
    NO_QUOTE (thiếu chào mua hoặc bán - hợp lệ khi khóa trần/sàn), LATE (tin đến muộn),
    NONCONT (ngoài phiên khớp liên tục)
"""
from __future__ import annotations

import math
from collections import Counter
from datetime import timedelta

from ..neo_api.models import LEVEL_FIELDS, NUMERIC_FIELDS, Snapshot
from ..timeutil import SessionCalendar, now_vn, to_vn

DROP_ISSUES = {"NO_SYMBOL", "BAD_TS", "FUTURE_TS", "DUPLICATE", "OUT_OF_ORDER", "NEG_VALUE",
               "CUM_DECREASE", "OUT_OF_BAND", "CROSSED_BOOK"}


def _num(x) -> float:
    try:
        v = float(x)
        return v if math.isfinite(v) else float("nan")
    except (TypeError, ValueError):
        return float("nan")


class QualityChecker:
    def __init__(self, calendar: SessionCalendar, max_future_s: float = 5.0,
                 late_after_s: float = 10.0, check_future: bool = True):
        self.cal = calendar
        self.max_future_s = max_future_s
        self.late_after_s = late_after_s
        self.check_future = check_future
        self.counts: Counter = Counter()
        self._prev: dict[str, Snapshot] = {}

    def check(self, snap: Snapshot) -> tuple[bool, list[str]]:
        """Trả về (chấp nhận?, danh sách cờ/sự cố)."""
        flags: list[str] = []

        def reject(code: str):
            self.counts[code] += 1
            return False, [code]

        if not snap.symbol:
            return reject("NO_SYMBOL")
        if snap.ts is None:
            return reject("BAD_TS")
        ts = to_vn(snap.ts)
        if self.check_future and ts > now_vn() + timedelta(seconds=self.max_future_s):
            return reject("FUTURE_TS")

        v = {k: _num(snap.values.get(k)) for k in NUMERIC_FIELDS}
        for k in NUMERIC_FIELDS:
            if v[k] < 0:
                return reject("NEG_VALUE")

        prev = self._prev.get(snap.symbol)
        if prev is not None:
            pts = to_vn(prev.ts)
            if ts == pts:
                return reject("DUPLICATE")
            if ts < pts:
                return reject("OUT_OF_ORDER")
            if pts.date() == ts.date():
                for k in ("cum_volume", "cum_value"):
                    a, b = _num(prev.values.get(k)), v[k]
                    if math.isfinite(a) and math.isfinite(b) and b < a:
                        return reject("CUM_DECREASE")

        phase = self.cal.phase(ts)
        floor_, ceil_ = v["floor"], v["ceiling"]
        if math.isfinite(floor_) and math.isfinite(ceil_) and ceil_ > 0:
            prices = [v["last"]] + [v[k] for k in LEVEL_FIELDS if k.endswith("_p")]
            for p in prices:
                if math.isfinite(p) and p > 0 and not (floor_ <= p <= ceil_):
                    return reject("OUT_OF_BAND")

        b1, a1 = v["bid1_p"], v["ask1_p"]
        if phase == "CONTINUOUS":
            if math.isfinite(b1) and math.isfinite(a1) and b1 > 0 and a1 > 0 and b1 >= a1:
                return reject("CROSSED_BOOK")
            if not (math.isfinite(b1) and b1 > 0 and math.isfinite(a1) and a1 > 0):
                flags.append("NO_QUOTE")
        else:
            flags.append("NONCONT")

        if snap.ingest_ts is not None:
            if (to_vn(snap.ingest_ts) - ts).total_seconds() > self.late_after_s:
                flags.append("LATE")

        self._prev[snap.symbol] = snap
        for f in flags:
            self.counts[f] += 1
        self.counts["ACCEPTED"] += 1
        return True, flags

    def phase_of(self, snap: Snapshot) -> str:
        return self.cal.phase(snap.ts)

    def drain_counts(self) -> dict[str, int]:
        c = dict(self.counts)
        self.counts.clear()
        return c
