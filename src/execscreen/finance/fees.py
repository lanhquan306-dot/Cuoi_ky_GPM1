"""Phí và thuế giao dịch (đơn vị bps)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeeSchedule:
    buy_bps: float = 15.0
    sell_bps: float = 15.0
    sell_tax_bps: float = 10.0

    @classmethod
    def from_config(cls, cfg: dict) -> "FeeSchedule":
        f = cfg["fees"]
        return cls(float(f["buy_bps"]), float(f["sell_bps"]), float(f["sell_tax_bps"]))

    @property
    def round_trip_bps(self) -> float:
        return self.buy_bps + self.sell_bps + self.sell_tax_bps
