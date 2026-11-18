"""Kiểm thử các hàm tài chính quan trọng bằng ví dụ tính tay."""
import numpy as np
import pandas as pd
import pytest

from execscreen.finance.execution import cost_table, walk_book
from execscreen.finance.fees import FeeSchedule
from execscreen.finance.microstructure import (mid_price, order_book_imbalance, parkinson_sigma_bps,
                                               spread_bps)
from execscreen.finance.ticks import price_limits, round_lot, round_to_tick, tick_size

ASKS = [(50_000, 1_000), (50_100, 2_000), (50_200, 5_000)]
BIDS = [(49_900, 1_000), (49_800, 2_000), (49_700, 5_000)]
MID = 49_950.0


def test_walk_book_buy_two_levels_hand_calc():
    r = walk_book(ASKS, "buy", 100_000_000, MID)
    assert r.target_shares == 2000          # floor(1e8 / 50000 / 100) * 100
    assert r.filled_shares == 2000
    assert r.vwap == pytest.approx((1000 * 50_000 + 1000 * 50_100) / 2000)   # 50 050
    assert r.slippage_bps == pytest.approx((50_050 / 49_950 - 1) * 1e4)      # ~20.02 bps
    assert r.levels_used == 2 and not r.beyond_depth and r.status == "OK"
    assert r.coverage == pytest.approx(8000 / 2000)


def test_walk_book_sell_hand_calc():
    r = walk_book(BIDS, "sell", 100_000_000, MID)
    assert r.target_shares == 2000
    assert r.vwap == pytest.approx(49_850)
    assert r.slippage_bps == pytest.approx((1 - 49_850 / 49_950) * 1e4)


def test_walk_book_beyond_depth_is_flagged_not_extrapolated():
    r = walk_book(ASKS, "buy", 600_000_000, MID)
    assert r.target_shares == 12_000
    assert r.filled_shares == 8_000          # chỉ khớp phần nhìn thấy
    assert r.beyond_depth and r.status == "PARTIAL"


def test_walk_book_edge_cases():
    assert walk_book([], "buy", 1e8, MID).status == "NO_QUOTE"
    assert walk_book(ASKS, "buy", 1_000_000, MID).status == "TOO_SMALL"   # < 1 lô
    assert walk_book([(0, 0), (None, 5)], "buy", 1e8, MID).status == "NO_QUOTE"


def _book_frame():
    return pd.DataFrame([{
        "symbol": "AAA", "bid1_p": 49_900, "bid1_v": 1_000, "bid2_p": 49_800, "bid2_v": 2_000,
        "bid3_p": 49_700, "bid3_v": 5_000, "ask1_p": 50_000, "ask1_v": 1_000, "ask2_p": 50_100,
        "ask2_v": 2_000, "ask3_p": 50_200, "ask3_v": 5_000, "high": 51_000, "low": 49_000}])


def test_cost_table_matches_scalar_and_round_trip_includes_fees():
    fees = FeeSchedule(15, 15, 10)
    ct = cost_table(_book_frame(), 100_000_000, 100, fees)
    s = walk_book(ASKS, "buy", 100_000_000, MID)
    assert ct["buy_slip_bps"].iloc[0] == pytest.approx(s.slippage_bps)
    assert ct["sell_slip_bps"].iloc[0] == pytest.approx((1 - 49_850 / 49_950) * 1e4)
    assert ct["rt_cost_bps"].iloc[0] == pytest.approx(
        ct["buy_slip_bps"].iloc[0] + ct["sell_slip_bps"].iloc[0] + 40)
    assert ct["spread_bps"].iloc[0] == pytest.approx(100 / 49_950 * 1e4)
    assert not ct["beyond"].iloc[0]


def test_cost_table_no_quote_gives_nan_not_guess():
    f = _book_frame()
    f.loc[0, ["ask1_p", "ask2_p", "ask3_p"]] = np.nan
    ct = cost_table(f, 100_000_000, 100, FeeSchedule())
    assert np.isnan(ct["rt_cost_bps"].iloc[0])


def test_cost_table_crossed_book_is_invalid():
    f = _book_frame()
    f.loc[0, "bid1_p"] = 50_100
    assert np.isnan(cost_table(f, 1e8, 100, FeeSchedule())["rt_cost_bps"].iloc[0])


def test_sqrt_impact_only_adds_cost_when_beyond_depth():
    fees = FeeSchedule()
    f = _book_frame()
    base = cost_table(f, 600_000_000, 100, fees, "flag")
    adv = pd.Series({"AAA": 5e9})
    ext = cost_table(f, 600_000_000, 100, fees, "sqrt_impact", 1.0, adv)
    assert ext["buy_slip_bps"].iloc[0] > base["buy_slip_bps"].iloc[0]
    same = cost_table(f, 100_000_000, 100, fees, "sqrt_impact", 1.0, adv)
    assert same["buy_slip_bps"].iloc[0] == pytest.approx(cost_table(f, 100_000_000, 100, fees)["buy_slip_bps"].iloc[0])


def test_microstructure_formulas():
    assert order_book_imbalance([[100, 50, 50]], [[50, 25, 25]])[0] == pytest.approx(100 / 300)
    assert np.isnan(order_book_imbalance([[0, 0, 0]], [[0, 0, 0]])[0])
    assert spread_bps(49_900, 50_000) == pytest.approx(100 / 49_950 * 1e4)
    assert np.isnan(spread_bps(50_100, 50_000))       # sổ chéo
    assert mid_price(49_900, 50_000) == pytest.approx(49_950)
    assert parkinson_sigma_bps(101, 100) == pytest.approx(np.log(1.01) / (2 * np.sqrt(np.log(2))) * 1e4)


def test_ticks_and_limits():
    assert [tick_size(p) for p in (9_990, 10_000, 49_950, 50_000)] == [10, 50, 50, 100]
    assert price_limits(50_000) == (46_500, 53_500)
    assert price_limits(20_000) == (18_600, 21_400)
    assert round_to_tick(20_024, direction="down") == 20_000
    assert round_lot(1_999) == 1_900
