"""Múi giờ Việt Nam (UTC+7) và phân loại phiên giao dịch.

Quy ước toàn dự án: mọi dấu thời gian lưu và hiển thị theo Asia/Ho_Chi_Minh.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

TZ_NAME = "Asia/Ho_Chi_Minh"
TZ = ZoneInfo(TZ_NAME)


def now_vn() -> datetime:
    return datetime.now(TZ)


def to_vn(dt: datetime) -> datetime:
    """Datetime không có múi giờ được coi là giờ Việt Nam."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)


def hhmm_to_sec(s: str) -> int:
    h, m = s.split(":")[:2]
    return int(h) * 3600 + int(m) * 60


def seconds_of_day(ts: pd.Series) -> pd.Series:
    """Giây trong ngày của chuỗi thời gian đã có múi giờ VN."""
    t = ts.dt.tz_convert(TZ_NAME)
    return t.dt.hour * 3600 + t.dt.minute * 60 + t.dt.second


@dataclass(frozen=True)
class SessionCalendar:
    ato: tuple[int, int]
    continuous: tuple[tuple[int, int], ...]
    atc: tuple[int, int]

    @classmethod
    def from_config(cls, cfg: dict) -> "SessionCalendar":
        s = cfg["sessions"]
        return cls(
            ato=(hhmm_to_sec(s["ato"][0]), hhmm_to_sec(s["ato"][1])),
            continuous=tuple((hhmm_to_sec(a), hhmm_to_sec(b)) for a, b in s["continuous"]),
            atc=(hhmm_to_sec(s["atc"][0]), hhmm_to_sec(s["atc"][1])),
        )

    def phase_of_seconds(self, sec: np.ndarray) -> np.ndarray:
        sec = np.asarray(sec)
        conds = [
            sec < self.ato[0],
            (sec >= self.ato[0]) & (sec < self.ato[1]),
        ]
        choices = ["PRE", "ATO"]
        for a, b in self.continuous:
            conds.append((sec >= a) & (sec < b))
            choices.append("CONTINUOUS")
        # nghỉ trưa: giữa hai phiên liên tục
        if len(self.continuous) >= 2:
            conds.append((sec >= self.continuous[0][1]) & (sec < self.continuous[1][0]))
            choices.append("BREAK")
        conds.append((sec >= self.atc[0]) & (sec <= self.atc[1]))
        choices.append("ATC")
        return np.select(conds, choices, default="CLOSED")

    def phase(self, dt: datetime) -> str:
        d = to_vn(dt)
        return str(self.phase_of_seconds(np.array([d.hour * 3600 + d.minute * 60 + d.second]))[0])

    def phase_series(self, ts: pd.Series) -> pd.Series:
        return pd.Series(self.phase_of_seconds(seconds_of_day(ts).to_numpy()), index=ts.index)

    def effective_sod(self, sec: int) -> int:
        """Quy giây trong ngày về mốc thuộc phiên liên tục gần nhất (dùng căn RVOL theo giờ)."""
        if len(self.continuous) >= 2:
            if self.continuous[0][1] <= sec < self.continuous[1][0]:
                return self.continuous[0][1]
        last_end = self.continuous[-1][1]
        return min(sec, last_end)
